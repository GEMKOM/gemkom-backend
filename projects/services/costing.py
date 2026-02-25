from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum


q2 = lambda x: Decimal(x).quantize(Decimal('0.01'))  # noqa: E731


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

    from core.models import CurrencyRateSnapshot

    snap = (
        CurrencyRateSnapshot.objects
        .filter(date__lte=on_date)
        .order_by('-date')
        .values('rates')
        .first()
    )
    if snap is None:
        # Fallback to earliest snapshot
        snap = CurrencyRateSnapshot.objects.order_by('date').values('rates').first()
    if snap is None:
        return Decimal('0.00')

    rates = snap['rates']  # {"EUR": X, "USD": Y, "GBP": Z} – all relative to TRY base

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
      labor_cost        = WeldingJobCostAgg.total_cost + sum(PartCostAgg.total_cost)
      material_cost     = sum(JobOrderProcurementLine.amount_eur)
      subcontractor_cost = non-paint SubcontractingAssignment costs converted to EUR
      paint_cost        = paint SubcontractingAssignment costs (approved statement lines
                          use statement.approved_at date for FX; unbilled portion uses today)
      qc_cost           = sum(JobOrderQCCostLine.amount_eur)
      shipping_cost     = sum(JobOrderShippingCostLine.amount_eur)
      actual_total_cost = sum of all above
    """
    from welding.models import WeldingJobCostAgg
    from tasks.models import PartCostAgg
    from subcontracting.models import SubcontractingAssignment, SubcontractorStatementLine
    from projects.models import (
        JobOrder, JobOrderCostSummary,
        JobOrderProcurementLine, JobOrderQCCostLine, JobOrderShippingCostLine,
    )

    today = date.today()

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

    labor = q2(Decimal(welding) + Decimal(machining))

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
        )
        .exclude(department_task__task_type='painting')
        .select_related('price_tier', 'department_task')
    )
    subcontractor = q2(sum(
        convert_to_eur(a.current_cost, a.cost_currency, today)
        for a in sc_assignments
    ))

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
    # 6. Total and upsert
    # ------------------------------------------------------------------
    total = q2(labor + material + subcontractor + paint + qc + shipping)

    JobOrderCostSummary.objects.update_or_create(
        job_order_id=job_no,
        defaults={
            'labor_cost': labor,
            'material_cost': material,
            'subcontractor_cost': subcontractor,
            'paint_cost': paint,
            'qc_cost': qc,
            'shipping_cost': shipping,
            'actual_total_cost': total,
        },
    )
