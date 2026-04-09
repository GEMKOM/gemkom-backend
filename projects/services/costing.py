from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache

from django.db import transaction
from django.db.models import Sum


q2 = lambda x: Decimal(x).quantize(Decimal('0.01'))  # noqa: E731


@lru_cache(maxsize=128)
def _fetch_rates(on_date: date) -> dict:
    """
    Return the rates dict from the CurrencyRateSnapshot nearest to on_date.
    Cached per date — historical rates never change, and 'today' becomes a
    different cache key each calendar day so it always fetches fresh data.
    """
    from core.models import CurrencyRateSnapshot

    snap = (
        CurrencyRateSnapshot.objects
        .filter(date__lte=on_date)
        .order_by('-date')
        .values('rates')
        .first()
    )
    if snap is None:
        snap = CurrencyRateSnapshot.objects.order_by('date').values('rates').first()
    return snap['rates'] if snap else {}


def convert_to_eur(amount: Decimal, currency: str, on_date: date) -> Decimal:
    """
    Convert an amount in any supported currency to EUR using CurrencyRateSnapshot.
    Uses the last snapshot on/before on_date (or earliest if none found before).
    Returns Decimal('0.00') if no snapshot is available or rate is missing.
    """
    if not amount:
        return Decimal('0.00')
    amount = Decimal(str(amount))
    if currency == 'EUR':
        return amount

    rates = _fetch_rates(on_date)  # single DB hit per date, then cached
    if not rates:
        return Decimal('0.00')

    if currency == 'TRY':
        eur_rate = Decimal(str(rates.get('EUR', 0)))
        if eur_rate == 0:
            return Decimal('0.00')
        return q2(amount * eur_rate)

    # Cross-rate via TRY: 1 src_currency = (rates['EUR'] / rates[src]) EUR
    eur_rate = Decimal(str(rates.get('EUR', 0)))
    src_rate = Decimal(str(rates.get(currency, 0)))
    if src_rate == 0 or eur_rate == 0:
        return Decimal('0.00')
    return q2(amount * (eur_rate / src_rate))


@transaction.atomic
def recompute_job_cost_summary(job_no: str) -> None:
    """
    Recompute and persist JobOrderCostSummary for the given job_no.

    Cost components (all in EUR):
      labor_cost          = WeldingJobCostAgg.total_cost + sum(PartCostAgg.total_cost)
      material_cost       = sum(JobOrderProcurementLine.amount_eur)
      subcontractor_cost  = non-paint SubcontractingAssignment costs + approved statement adjustments (job-linked) converted to EUR
      paint_cost          = paint SubcontractingAssignment costs (approved statement lines
                            use statement.approved_at date for FX; unbilled portion uses today)
      qc_cost             = sum(JobOrderQCCostLine.amount_eur)
      shipping_cost       = sum(JobOrderShippingCostLine.amount_eur)
      paint_material_cost = 4.00 TRY × total_weight_kg → EUR (only if painting task not skipped)
      general_expenses_cost = general_expenses_rate (TRY/kg) × total_weight_kg → EUR
      employee_overhead_cost = employee_overhead_rate × own labor_cost
      actual_total_cost   = sum of all above
    """
    from welding.models import WeldingJobCostAgg
    from tasks.models import PartCostAgg
    from subcontracting.models import SubcontractingAssignment, SubcontractorStatementLine, SubcontractorStatementAdjustment
    from projects.models import (
        JobOrder, JobOrderCostSummary,
        JobOrderProcurementLine, JobOrderQCCostLine, JobOrderShippingCostLine,
        JobOrderDepartmentTask,
    )

    today = date.today()

    # ------------------------------------------------------------------
    # 0. Fetch job order fields needed for new cost components
    # ------------------------------------------------------------------
    job_fields = (
        JobOrder.objects
        .values('total_weight_kg', 'general_expenses_rate')
        .filter(job_no=job_no)
        .first()
    )
    if job_fields is None:
        return
    total_weight_kg = Decimal(str(job_fields['total_weight_kg'] or 0))
    general_expenses_rate = Decimal(str(job_fields['general_expenses_rate'] or 0))

    # ------------------------------------------------------------------
    # 1. Labor = welding + machining (both already stored in EUR)
    # ------------------------------------------------------------------
    welding = (
        WeldingJobCostAgg.objects
        .filter(job_no=job_no)
        .values_list('total_cost', flat=True)
        .first()
    ) or Decimal('0')

    machining = (
        PartCostAgg.objects
        .filter(job_no_cached=job_no)
        .aggregate(s=Sum('total_cost'))['s']
    ) or Decimal('0')

    own_labor = q2(Decimal(welding) + Decimal(machining))
    labor = own_labor

    # ------------------------------------------------------------------
    # 2. Material = sum of saved procurement lines (unit_price is EUR)
    # ------------------------------------------------------------------
    material = q2(
        JobOrderProcurementLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    # ------------------------------------------------------------------
    # 3. Subcontractor = non-paint assignments with price_tier + weight
    # ------------------------------------------------------------------
    sc_assignments = (
        SubcontractingAssignment.objects
        .filter(
            department_task__job_order_id=job_no,
            price_tier__isnull=False,
            allocated_weight_kg__gt=0,
            is_retired=False,
        )
        .exclude(department_task__task_type='painting')
        .select_related('price_tier', 'department_task')
    )
    subcontractor = q2(sum(
        convert_to_eur(a.current_cost, a.cost_currency, today)
        for a in sc_assignments
    ))

    # Add approved statement adjustments linked to this job order
    sc_adjustments = (
        SubcontractorStatementAdjustment.objects
        .filter(
            job_order_id=job_no,
            statement__status='approved',
        )
        .select_related('statement')
    )
    for adj in sc_adjustments:
        subcontractor += convert_to_eur(adj.amount, adj.statement.currency, adj.statement.approved_at.date())
    subcontractor = q2(subcontractor)

    # ------------------------------------------------------------------
    # 4. Paint = paint assignments
    #    Billed portion: approved statement lines → use statement.approved_at for FX
    #    Unbilled portion: use today's rate
    # ------------------------------------------------------------------
    paint_statement_lines = (
        SubcontractorStatementLine.objects
        .filter(
            assignment__department_task__job_order_id=job_no,
            assignment__department_task__task_type='painting',
            statement__status='approved',
        )
        .select_related('statement', 'assignment')
    )
    paint_billed = sum(
        convert_to_eur(
            line.cost_amount,
            line.assignment.cost_currency,
            line.statement.approved_at.date(),
        )
        for line in paint_statement_lines
        if line.statement.approved_at
    )

    paint_assignments = (
        SubcontractingAssignment.objects
        .filter(
            department_task__job_order_id=job_no,
            department_task__task_type='painting',
            price_tier__isnull=False,
            allocated_weight_kg__gt=0,
            is_retired=False,
        )
        .select_related('price_tier', 'department_task')
    )
    paint_unbilled = sum(
        convert_to_eur(a.unbilled_cost, a.cost_currency, today)
        for a in paint_assignments
    )

    paint = q2(Decimal(paint_billed) + Decimal(paint_unbilled))

    # ------------------------------------------------------------------
    # 5. QC and Shipping (amount_eur already stored by user)
    # ------------------------------------------------------------------
    qc = q2(
        JobOrderQCCostLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    shipping = q2(
        JobOrderShippingCostLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    # ------------------------------------------------------------------
    # 6. Paint material cost = paint_material_rate (TRY/kg) × total_weight_kg → EUR
    #    Only if job has at least one non-skipped painting task
    #    Preserve user-customized rate; fall back to default 4.00
    # ------------------------------------------------------------------
    existing = JobOrderCostSummary.objects.filter(job_order_id=job_no).values(
        'paint_material_rate', 'employee_overhead_rate'
    ).first()

    paint_material_rate = (
        Decimal(str(existing['paint_material_rate']))
        if existing else Decimal('4.00')
    )

    painting_task = (
        JobOrderDepartmentTask.objects
        .filter(job_order_id=job_no, task_type='painting')
        .exclude(status='skipped')
        .values('manual_progress')
        .first()
    )
    painting_progress = Decimal(str(painting_task['manual_progress'] or 0)) if painting_task else Decimal('0')
    paint_material = q2(
        convert_to_eur(paint_material_rate * total_weight_kg * (painting_progress / Decimal('100')), 'TRY', today)
        if (total_weight_kg > 0 and painting_progress > 0) else Decimal('0')
    )

    # ------------------------------------------------------------------
    # 7. General expenses = general_expenses_rate (EUR/kg) × total_weight_kg
    # ------------------------------------------------------------------
    general_expenses = q2(
        general_expenses_rate * total_weight_kg
        if (general_expenses_rate > 0 and total_weight_kg > 0) else Decimal('0')
    )

    # ------------------------------------------------------------------
    # 8. Employee overhead = employee_overhead_rate × own labor_cost
    #    Preserve user-customized rate; fall back to default 0.65
    # ------------------------------------------------------------------
    employee_overhead_rate = (
        Decimal(str(existing['employee_overhead_rate']))
        if existing else Decimal('0.65')
    )
    employee_overhead = q2(employee_overhead_rate * own_labor)

    # ------------------------------------------------------------------
    # 9. Add direct children's rolled-up costs
    #    Each child's summary already includes its own descendants, so
    #    summing direct children avoids double-counting.
    # ------------------------------------------------------------------
    children_summaries = list(
        JobOrderCostSummary.objects.filter(job_order__parent_id=job_no)
    )
    if children_summaries:
        labor             += sum(s.labor_cost             for s in children_summaries)
        material          += sum(s.material_cost          for s in children_summaries)
        subcontractor     += sum(s.subcontractor_cost     for s in children_summaries)
        paint             += sum(s.paint_cost             for s in children_summaries)
        qc                += sum(s.qc_cost               for s in children_summaries)
        shipping          += sum(s.shipping_cost          for s in children_summaries)
        paint_material    += sum(s.paint_material_cost    for s in children_summaries)
        general_expenses  += sum(s.general_expenses_cost  for s in children_summaries)
        employee_overhead += sum(s.employee_overhead_cost for s in children_summaries)

    # ------------------------------------------------------------------
    # 10. Total and upsert
    # ------------------------------------------------------------------
    total = q2(
        labor + material + subcontractor + paint + qc + shipping
        + paint_material + general_expenses + employee_overhead
    )

    JobOrderCostSummary.objects.update_or_create(
        job_order_id=job_no,
        defaults={
            'labor_cost': q2(labor),
            'material_cost': q2(material),
            'subcontractor_cost': q2(subcontractor),
            'paint_cost': q2(paint),
            'qc_cost': q2(qc),
            'shipping_cost': q2(shipping),
            'paint_material_cost': q2(paint_material),
            'general_expenses_cost': q2(general_expenses),
            'employee_overhead_cost': q2(employee_overhead),
            'actual_total_cost': total,
        },
    )

    # ------------------------------------------------------------------
    # 11. Chain up: if this job has a parent, recompute the parent too
    # ------------------------------------------------------------------
    parent_id = (
        JobOrder.objects
        .values_list('parent_id', flat=True)
        .get(job_no=job_no)
    )
    if parent_id:
        recompute_job_cost_summary(parent_id)
