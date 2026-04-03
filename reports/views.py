from __future__ import annotations

import datetime
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum, Count, Avg, Q, F, ExpressionWrapper, BigIntegerField
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from procurement.reports.common import get_fallback_rates, to_eur


# ---------------------------------------------------------------------------
# Date range helpers
# ---------------------------------------------------------------------------

VALID_PRESETS = {'current_month', 'last_3_months', 'last_6_months', 'last_year'}


def _resolve_date_range(
    preset: str | None,
    date_from_str: str | None,
    date_to_str: str | None,
) -> tuple[datetime.date, datetime.date, str | None]:
    """
    Returns (date_from, date_to, used_preset).
    Priority: preset > explicit dates > default (current_month).
    """
    today = timezone.now().date()

    if preset and preset in VALID_PRESETS:
        if preset == 'current_month':
            date_from = today.replace(day=1)
            date_to = today
        elif preset == 'last_3_months':
            date_from = (today - datetime.timedelta(days=91)).replace(day=1)
            date_to = today
        elif preset == 'last_6_months':
            date_from = (today - datetime.timedelta(days=182)).replace(day=1)
            date_to = today
        else:  # last_year
            date_from = today.replace(month=1, day=1) - datetime.timedelta(days=365 - 365)
            date_from = datetime.date(today.year - 1, today.month, 1)
            date_to = today
        return date_from, date_to, preset

    if date_from_str and date_to_str:
        try:
            date_from = datetime.date.fromisoformat(date_from_str)
            date_to = datetime.date.fromisoformat(date_to_str)
            if date_from > date_to:
                date_from, date_to = date_to, date_from
            return date_from, date_to, None
        except ValueError:
            pass

    # default: current month
    date_from = today.replace(day=1)
    date_to = today
    return date_from, date_to, 'current_month'


def _q2(val) -> str:
    """Round to 2dp and return as string for JSON serialisation."""
    if val is None:
        return '0.00'
    return str(Decimal(str(val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _job_orders_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from projects.models import JobOrder

    active_qs = JobOrder.objects.filter(parent__isnull=True, status='active')
    completed_qs = JobOrder.objects.filter(
        parent__isnull=True,
        status='completed',
        completed_at__date__gte=date_from,
        completed_at__date__lte=date_to,
    )
    started_qs = JobOrder.objects.filter(
        parent__isnull=True,
        started_at__date__gte=date_from,
        started_at__date__lte=date_to,
    )
    overdue_qs = JobOrder.objects.filter(
        parent__isnull=True,
        status='active',
        target_completion_date__lt=date_to,
        target_completion_date__isnull=False,
    )

    avg_completion = active_qs.aggregate(avg=Avg('completion_percentage'))['avg']

    by_status = dict(
        JobOrder.objects.filter(parent__isnull=True)
        .values('status')
        .annotate(n=Count('pk'))
        .values_list('status', 'n')
    )

    return {
        'total_active': active_qs.count(),
        'total_completed_in_range': completed_qs.count(),
        'total_started_in_range': started_qs.count(),
        'overdue': overdue_qs.count(),
        'avg_completion_pct': _q2(avg_completion),
        'by_status': by_status,
    }


def _sales_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from sales.models import SalesOffer, SalesOfferPriceRevision

    created_qs = SalesOffer.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    won_qs = SalesOffer.objects.filter(
        won_at__date__gte=date_from,
        won_at__date__lte=date_to,
    )
    lost_qs = SalesOffer.objects.filter(
        lost_at__date__gte=date_from,
        lost_at__date__lte=date_to,
    )

    # Sum won offer amounts from current price revisions (EUR)
    won_value = (
        SalesOfferPriceRevision.objects
        .filter(
            offer__in=won_qs,
            is_current=True,
            currency='EUR',
        )
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )

    pipeline_statuses = ['consultation', 'pricing', 'pending_approval', 'submitted_customer']
    pipeline = dict(
        SalesOffer.objects.filter(status__in=pipeline_statuses)
        .values('status')
        .annotate(n=Count('pk'))
        .values_list('status', 'n')
    )
    for s in pipeline_statuses:
        pipeline.setdefault(s, 0)

    return {
        'offers_created_in_range': created_qs.count(),
        'offers_won_in_range': won_qs.count(),
        'offers_lost_in_range': lost_qs.count(),
        'total_won_value_eur': _q2(won_value),
        'pipeline_by_stage': pipeline,
    }


def _design_revisions_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from projects.models import JobOrderDiscussionTopic, JobOrder

    revision_qs = JobOrderDiscussionTopic.objects.filter(topic_type='revision_request')

    requested = revision_qs.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).count()

    approved_in_range = revision_qs.filter(
        revision_status='in_progress',
        updated_at__date__gte=date_from,
        updated_at__date__lte=date_to,
    ).count()

    completed_in_range = revision_qs.filter(
        revision_status='resolved',
        updated_at__date__gte=date_from,
        updated_at__date__lte=date_to,
    ).count()

    rejected_in_range = revision_qs.filter(
        revision_status='rejected',
        updated_at__date__gte=date_from,
        updated_at__date__lte=date_to,
    ).count()

    pending = revision_qs.filter(revision_status='pending').count()

    jobs_on_hold = JobOrder.objects.filter(
        status='on_hold',
        discussion_topics__topic_type='revision_request',
        discussion_topics__revision_status='in_progress',
        discussion_topics__is_deleted=False,
    ).distinct().count()

    return {
        'revisions_requested_in_range': requested,
        'revisions_approved_in_range': approved_in_range,
        'revisions_completed_in_range': completed_in_range,
        'revisions_rejected_in_range': rejected_in_range,
        'revisions_pending': pending,
        'jobs_currently_on_hold_for_revision': jobs_on_hold,
    }


def _costs_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from projects.models import JobOrderCostSummary, JobOrder

    active_jobs_qs = JobOrder.objects.filter(
        parent__isnull=True,
    ).exclude(job_no='LEGACY-ARCHIVE')

    summaries = JobOrderCostSummary.objects.filter(
        job_order__in=active_jobs_qs,
        cost_not_applicable=False,
    )

    agg = summaries.aggregate(
        total_actual=Sum('actual_total_cost'),
        total_sub=Sum('subcontractor_cost'),
        total_mat=Sum('material_cost'),
        total_labor=Sum('labor_cost'),
    )

    jobs_with_price_agg = summaries.filter(selling_price__gt=0).aggregate(
        total_selling=Sum('selling_price'),
        count=Count('pk'),
    )
    jobs_with_cost_data = summaries.count()
    jobs_with_selling_price = jobs_with_price_agg['count'] or 0
    total_selling_eur = jobs_with_price_agg['total_selling'] or Decimal('0')

    margins = []
    for s in summaries.filter(selling_price__gt=0).only('actual_total_cost', 'selling_price'):
        margin = (s.selling_price - s.actual_total_cost) / s.selling_price * 100
        margins.append(margin)

    avg_margin = sum(margins) / len(margins) if margins else None

    return {
        'jobs_with_cost_data': jobs_with_cost_data,
        'jobs_with_selling_price': jobs_with_selling_price,
        'total_actual_cost_eur': _q2(agg['total_actual']),
        'total_selling_price_eur': _q2(total_selling_eur),
        'total_subcontractor_cost_eur': _q2(agg['total_sub']),
        'total_material_cost_eur': _q2(agg['total_mat']),
        'total_labor_cost_eur': _q2(agg['total_labor']),
        'avg_margin_pct': _q2(avg_margin),
    }


def _subcontracting_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from subcontracting.models import (
        SubcontractorStatement, SubcontractorStatementLine,
        SubcontractorStatementAdjustment, SubcontractingAssignment,
    )

    approved_qs = SubcontractorStatement.objects.filter(
        status='approved',
        approved_at__date__gte=date_from,
        approved_at__date__lte=date_to,
    )
    paid_qs = SubcontractorStatement.objects.filter(
        status='paid',
        paid_at__date__gte=date_from,
        paid_at__date__lte=date_to,
    )
    pending_count = SubcontractorStatement.objects.filter(status='submitted').count()

    approved_agg = approved_qs.aggregate(total=Sum('grand_total'))
    paid_agg = paid_qs.aggregate(total=Sum('grand_total'))

    # Total awarded tonnage in range: line item weight + adjustment weight
    total_work_weight = (
        SubcontractorStatementLine.objects
        .filter(statement__in=approved_qs)
        .aggregate(total=Sum('effective_weight_kg'))['total'] or Decimal('0')
    )
    total_adj_weight = (
        SubcontractorStatementAdjustment.objects
        .filter(statement__in=approved_qs)
        .aggregate(total=Sum('weight_kg'))['total'] or Decimal('0')
    )

    # Per-subcontractor breakdown: financial total + tonnage, merged from lines and adjustments
    line_rows = {
        row['statement__subcontractor__name']: row
        for row in SubcontractorStatementLine.objects.filter(
            statement__in=approved_qs,
        ).values('statement__subcontractor__name').annotate(
            work_weight_kg=Sum('effective_weight_kg'),
            work_total=Sum('cost_amount'),
        )
    }
    adj_rows = {}
    for row in SubcontractorStatementAdjustment.objects.filter(
        statement__in=approved_qs,
    ).values('statement__subcontractor__name').annotate(
        adj_weight_kg=Sum('weight_kg'),
        adj_total=Sum('amount'),
    ):
        adj_rows[row['statement__subcontractor__name']] = row

    # Currency comes from the statement; fetch it separately for the breakdown
    currency_by_sub = dict(
        approved_qs.values_list('subcontractor__name', 'currency').distinct()
    )

    all_names = set(line_rows.keys()) | set(adj_rows.keys())
    by_sub_out = []
    for name in all_names:
        lin = line_rows.get(name, {})
        adj = adj_rows.get(name, {})
        work_weight = lin.get('work_weight_kg') or Decimal('0')
        adj_weight = adj.get('adj_weight_kg') or Decimal('0')
        approved_total = (lin.get('work_total') or Decimal('0')) + (adj.get('adj_total') or Decimal('0'))
        by_sub_out.append({
            'name': name,
            'approved_total': _q2(approved_total),
            'currency': currency_by_sub.get(name, ''),
            'work_weight_kg': _q2(work_weight),
            'adjustment_weight_kg': _q2(adj_weight),
            'total_awarded_weight_kg': _q2(work_weight + adj_weight),
        })
    by_sub_out.sort(key=lambda x: x['approved_total'], reverse=True)
    by_sub_out = by_sub_out[:10]

    # Unbilled accrual — sum unbilled_cost property across all active assignments.
    # Computed in Python (property, not DB field); only active (non-painting) assignments.
    fallback_rates = get_fallback_rates()
    total_unbilled = Decimal('0')
    assignments = SubcontractingAssignment.objects.select_related(
        'price_tier', 'department_task'
    ).filter(price_tier__price_per_kg__gt=0)
    for a in assignments:
        unbilled = a.unbilled_cost
        if unbilled > 0:
            eur = to_eur(unbilled, a.cost_currency, {}, fallback_rates)
            if eur is not None:
                total_unbilled += eur

    return {
        'statements_approved_in_range': approved_qs.count(),
        'statements_paid_in_range': paid_qs.count(),
        'total_approved_value': _q2(approved_agg['total']),
        'total_paid_value': _q2(paid_agg['total']),
        'pending_statements': pending_count,
        'total_unbilled_accrual_eur': _q2(total_unbilled),
        'total_awarded_weight_kg': _q2(total_work_weight + total_adj_weight),
        'by_subcontractor': by_sub_out,
    }


def _procurement_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from procurement.models import PurchaseRequest, PurchaseOrder, PaymentSchedule

    pr_count = PurchaseRequest.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
        status='submitted',
    ).count()

    po_qs = PurchaseOrder.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    po_count = po_qs.count()

    # Convert PO totals to EUR
    fallback_rates = get_fallback_rates()
    total_ordered_eur = Decimal('0')
    for po in po_qs.only('total_amount', 'currency'):
        eur = to_eur(po.total_amount, po.currency, {}, fallback_rates)
        if eur is not None:
            total_ordered_eur += eur

    today = timezone.now().date()
    payments_due = PaymentSchedule.objects.filter(
        due_date__gte=date_from,
        due_date__lte=date_to,
        is_paid=False,
    )
    payments_overdue = PaymentSchedule.objects.filter(
        due_date__lt=today,
        is_paid=False,
    )

    # Sum due payments in EUR
    total_due_eur = Decimal('0')
    for ps in payments_due.select_related('purchase_order').only(
        'amount', 'currency', 'purchase_order'
    ):
        eur = to_eur(ps.amount, ps.currency, {}, fallback_rates)
        if eur is not None:
            total_due_eur += eur

    return {
        'requests_submitted_in_range': pr_count,
        'orders_created_in_range': po_count,
        'total_ordered_value_eur': _q2(total_ordered_eur),
        'payments_due_in_range': payments_due.count(),
        'payments_overdue': payments_overdue.count(),
        'total_payments_due_eur': _q2(total_due_eur),
    }


def _manufacturing_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from welding.models import WeldingTimeEntry
    from tasks.models import Timer, Part, Operation
    from django.contrib.contenttypes.models import ContentType
    from cnc_cutting.models import CncTask

    # ms range in UTC
    date_from_ms = int(datetime.datetime(date_from.year, date_from.month, date_from.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    date_to_ms = int(datetime.datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    # ── Welding ───────────────────────────────────────────────────────────────
    welding_qs = WeldingTimeEntry.objects.filter(date__gte=date_from, date__lte=date_to)
    welding_hours = welding_qs.aggregate(total=Sum('hours'))['total'] or Decimal('0')
    welding_users = welding_qs.values('employee').distinct().count()

    # ── Machining (Parts + Operations) ────────────────────────────────────────
    # Task counts: Part is the unit of work; Operation holds the timers
    machining_parts_completed = Part.objects.filter(
        completion_date__gte=date_from_ms,
        completion_date__lte=date_to_ms,
    ).count()
    machining_parts_remaining = Part.objects.filter(completion_date__isnull=True).count()

    op_ct = ContentType.objects.get_for_model(Operation)
    machining_timer_qs = Timer.objects.filter(
        content_type=op_ct,
        timer_type='productive',
        start_time__gte=date_from_ms,
        start_time__lte=date_to_ms,
        finish_time__isnull=False,
    )
    machining_ms = machining_timer_qs.aggregate(total=Sum(ExpressionWrapper(
        F('finish_time') - F('start_time'),
        output_field=BigIntegerField(),
    )))['total'] or 0
    machining_hours = _q2(Decimal(machining_ms) / Decimal('3600000'))
    machining_users = machining_timer_qs.values('user').distinct().count()

    # ── CNC ───────────────────────────────────────────────────────────────────
    cnc_ct = ContentType.objects.get_for_model(CncTask)
    cnc_timer_qs = Timer.objects.filter(
        content_type=cnc_ct,
        timer_type='productive',
        start_time__gte=date_from_ms,
        start_time__lte=date_to_ms,
        finish_time__isnull=False,
    )
    cnc_ms = cnc_timer_qs.aggregate(total=Sum(ExpressionWrapper(
        F('finish_time') - F('start_time'),
        output_field=BigIntegerField(),
    )))['total'] or 0
    cnc_hours = _q2(Decimal(cnc_ms) / Decimal('3600000'))
    cnc_users = cnc_timer_qs.values('user').distinct().count()

    cnc_completed = CncTask.objects.filter(
        completion_date__gte=date_from_ms,
        completion_date__lte=date_to_ms,
    ).count()
    cnc_remaining = CncTask.objects.filter(completion_date__isnull=True).count()

    total_hours = _q2(Decimal(welding_hours) + Decimal(machining_hours) + Decimal(cnc_hours))

    # ── Manufactured Tonnage ──────────────────────────────────────────────────
    # Summed from JobOrderProgressLog: delta_weight_kg = total_weight_kg × Δ% / 100
    # Only positive deltas (forward progress). Entries with no total_weight_kg are excluded.
    from projects.models import JobOrderProgressLog
    tonnage_agg = JobOrderProgressLog.objects.filter(
        logged_at__date__gte=date_from,
        logged_at__date__lte=date_to,
        delta_weight_kg__isnull=False,
        delta_weight_kg__gt=0,
    ).aggregate(total=Sum('delta_weight_kg'))
    manufactured_tonnage_kg = _q2(tonnage_agg['total'] or Decimal('0'))

    return {
        'welding_hours': _q2(welding_hours),
        'welding_active_users': welding_users,
        'machining_hours': machining_hours,
        'machining_active_users': machining_users,
        'machining_parts_completed': machining_parts_completed,
        'machining_parts_remaining': machining_parts_remaining,
        'cnc_hours': cnc_hours,
        'cnc_active_users': cnc_users,
        'cnc_tasks_completed': cnc_completed,
        'cnc_tasks_remaining': cnc_remaining,
        'total_productive_hours': total_hours,
        'manufactured_tonnage_kg': manufactured_tonnage_kg,
    }


def _quality_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from quality_control.models import NCR, QCReview

    ncr_base = NCR.objects.exclude(job_order__job_no='LEGACY-ARCHIVE')

    ncrs_opened = ncr_base.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).count()

    ncrs_closed = ncr_base.filter(
        status='closed',
        updated_at__date__gte=date_from,
        updated_at__date__lte=date_to,
    ).count()

    ncrs_open_total = ncr_base.exclude(status='closed').count()

    severity_counts = dict(
        ncr_base.exclude(status='closed')
        .values('severity')
        .annotate(n=Count('pk'))
        .values_list('severity', 'n')
    )

    defect_counts = dict(
        ncr_base.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        .values('defect_type')
        .annotate(n=Count('pk'))
        .values_list('defect_type', 'n')
    )

    qc_in_range = QCReview.objects.filter(
        submitted_at__date__gte=date_from,
        submitted_at__date__lte=date_to,
    )
    qc_approved = qc_in_range.filter(status='approved').count()
    qc_rejected = qc_in_range.filter(status='rejected').count()

    return {
        'ncrs_opened_in_range': ncrs_opened,
        'ncrs_closed_in_range': ncrs_closed,
        'ncrs_open_total': ncrs_open_total,
        'ncrs_by_severity': severity_counts,
        'ncrs_by_defect_type': defect_counts,
        'qc_reviews_in_range': qc_in_range.count(),
        'qc_reviews_approved': qc_approved,
        'qc_reviews_rejected': qc_rejected,
    }


def _overtime_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from overtime.models import OvertimeRequest, OvertimeEntry

    # Filter by start_at (when overtime occurred), not created_at (when filed)
    in_range_qs = OvertimeRequest.objects.filter(
        start_at__date__gte=date_from,
        start_at__date__lte=date_to,
    )
    approved_qs = in_range_qs.filter(status='approved')

    total_hours = (
        approved_qs.aggregate(total=Sum('duration_hours'))['total'] or Decimal('0')
    )

    by_team = list(
        approved_qs
        .values('team')
        .annotate(total_hours=Sum('duration_hours'))
        .order_by('-total_hours')
        .values('team', 'total_hours')
    )
    by_team_out = [
        {'team': row['team'], 'hours': _q2(row['total_hours'])}
        for row in by_team
        if row['total_hours'] is not None
    ]

    return {
        'requests_in_range': in_range_qs.count(),
        'requests_approved_in_range': approved_qs.count(),
        'total_approved_hours': _q2(total_hours),
        'by_team': by_team_out,
    }


def _maintenance_section(date_from: datetime.date, date_to: datetime.date) -> dict:
    from machines.models import MachineFault
    from tasks.models import Timer

    date_from_ms = int(datetime.datetime(date_from.year, date_from.month, date_from.day, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    date_to_ms = int(datetime.datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    reported_qs = MachineFault.objects.filter(
        reported_at__date__gte=date_from,
        reported_at__date__lte=date_to,
    )
    resolved_qs = MachineFault.objects.filter(
        resolved_at__date__gte=date_from,
        resolved_at__date__lte=date_to,
    )
    open_qs = MachineFault.objects.filter(resolved_at__isnull=True)

    # Downtime hours for faults resolved in range (both fields must be set)
    downtime_ms = resolved_qs.filter(
        downtime_start_ms__isnull=False,
        downtime_end_ms__isnull=False,
    ).aggregate(
        total=Sum(ExpressionWrapper(
            F('downtime_end_ms') - F('downtime_start_ms'),
            output_field=BigIntegerField(),
        ))
    )['total'] or 0
    downtime_hours = _q2(Decimal(downtime_ms) / Decimal('3600000'))

    # Maintenance work hours: productive timers linked to MachineFault via GFK
    from django.contrib.contenttypes.models import ContentType
    fault_ct = ContentType.objects.get_for_model(MachineFault)
    maintenance_timer_qs = Timer.objects.filter(
        content_type=fault_ct,
        timer_type='productive',
        start_time__gte=date_from_ms,
        start_time__lte=date_to_ms,
        finish_time__isnull=False,
    )
    maintenance_ms = maintenance_timer_qs.aggregate(
        total=Sum(ExpressionWrapper(
            F('finish_time') - F('start_time'),
            output_field=BigIntegerField(),
        ))
    )['total'] or 0
    maintenance_hours = _q2(Decimal(maintenance_ms) / Decimal('3600000'))
    maintenance_active_users = maintenance_timer_qs.values('user').distinct().count()

    return {
        'faults_reported_in_range': reported_qs.count(),
        'faults_reported_breaking': reported_qs.filter(is_breaking=True).count(),
        'faults_reported_maintenance': reported_qs.filter(is_maintenance=True).count(),
        'faults_resolved_in_range': resolved_qs.count(),
        'faults_open': open_qs.count(),
        'faults_open_breaking': open_qs.filter(is_breaking=True).count(),
        'downtime_hours_in_range': downtime_hours,
        'maintenance_hours': maintenance_hours,
        'maintenance_active_users': maintenance_active_users,
    }


# ---------------------------------------------------------------------------
# Shared request parsing helper
# ---------------------------------------------------------------------------

def _parse_request(request):
    """
    Parse preset/date_from/date_to/compare from a request.
    Returns (date_from, date_to, meta, compare, prev_date_from, prev_date_to)
    or raises Response on bad input.
    """
    preset = request.query_params.get('preset')
    date_from_str = request.query_params.get('date_from')
    date_to_str = request.query_params.get('date_to')
    compare = request.query_params.get('compare') == 'true'

    if preset and preset not in VALID_PRESETS:
        return None, None, None, None, None, None, Response(
            {'detail': f"Invalid preset. Choose from: {', '.join(sorted(VALID_PRESETS))}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    date_from, date_to, used_preset = _resolve_date_range(preset, date_from_str, date_to_str)

    meta = {
        'preset': used_preset,
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
        'compare': compare,
    }

    prev_date_from = prev_date_to = None
    if compare:
        delta = date_to - date_from
        prev_date_to = date_from - datetime.timedelta(days=1)
        prev_date_from = prev_date_to - delta
        meta['prev_date_from'] = prev_date_from.isoformat()
        meta['prev_date_to'] = prev_date_to.isoformat()

    return date_from, date_to, meta, compare, prev_date_from, prev_date_to, None


# ---------------------------------------------------------------------------
# Individual section endpoints
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def operations_report(request):
    """GET /reports/operations/ — manufacturing, maintenance, overtime, quality, design_revisions"""
    date_from, date_to, meta, compare, prev_from, prev_to, err = _parse_request(request)
    if err:
        return err

    data = {
        'meta': meta,
        'manufacturing': _manufacturing_section(date_from, date_to),
        'maintenance': _maintenance_section(date_from, date_to),
        'overtime': _overtime_section(date_from, date_to),
        'quality': _quality_section(date_from, date_to),
        'design_revisions': _design_revisions_section(date_from, date_to),
    }
    if compare:
        data['previous_period'] = {
            'manufacturing': _manufacturing_section(prev_from, prev_to),
            'maintenance': _maintenance_section(prev_from, prev_to),
            'overtime': _overtime_section(prev_from, prev_to),
            'quality': _quality_section(prev_from, prev_to),
            'design_revisions': _design_revisions_section(prev_from, prev_to),
        }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def subcontracting_report(request):
    """GET /reports/subcontracting/"""
    date_from, date_to, meta, compare, prev_from, prev_to, err = _parse_request(request)
    if err:
        return err

    data = {
        'meta': meta,
        'subcontracting': _subcontracting_section(date_from, date_to),
    }
    if compare:
        data['previous_period'] = {
            'subcontracting': _subcontracting_section(prev_from, prev_to),
        }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def procurement_report(request):
    """GET /reports/procurement/"""
    date_from, date_to, meta, compare, prev_from, prev_to, err = _parse_request(request)
    if err:
        return err

    data = {
        'meta': meta,
        'procurement': _procurement_section(date_from, date_to),
    }
    if compare:
        data['previous_period'] = {
            'procurement': _procurement_section(prev_from, prev_to),
        }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_report(request):
    """GET /reports/sales/"""
    date_from, date_to, meta, compare, prev_from, prev_to, err = _parse_request(request)
    if err:
        return err

    data = {
        'meta': meta,
        'sales': _sales_section(date_from, date_to),
    }
    if compare:
        data['previous_period'] = {
            'sales': _sales_section(prev_from, prev_to),
        }
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_orders_report(request):
    """GET /reports/job-orders/ — job_orders + costs"""
    date_from, date_to, meta, compare, prev_from, prev_to, err = _parse_request(request)
    if err:
        return err

    data = {
        'meta': meta,
        'job_orders': _job_orders_section(date_from, date_to),
        'costs': _costs_section(date_from, date_to),
    }
    if compare:
        data['previous_period'] = {
            'job_orders': _job_orders_section(prev_from, prev_to),
            'costs': _costs_section(prev_from, prev_to),
        }
    return Response(data)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def snapshot(request):
    from projects.models import JobOrder, JobOrderDepartmentTask
    from overtime.models import OvertimeRequest
    from procurement.models import PurchaseRequest, PaymentSchedule
    from subcontracting.models import SubcontractorStatement
    from quality_control.models import NCR

    today = timezone.now().date()

    active_qs = JobOrder.objects.filter(parent__isnull=True, status='active')

    return Response({
        'job_orders': {
            'active': active_qs.count(),
            'overdue': active_qs.filter(
                target_completion_date__lt=today,
                target_completion_date__isnull=False,
            ).count(),
            'on_hold_for_revision': JobOrder.objects.filter(
                status='on_hold',
                discussion_topics__topic_type='revision_request',
                discussion_topics__revision_status='in_progress',
                discussion_topics__is_deleted=False,
            ).distinct().count(),
        },
        'approvals_pending': {
            'overtime_requests': OvertimeRequest.objects.filter(status='submitted').count(),
            'purchase_requests': PurchaseRequest.objects.filter(status='submitted').count(),
            'subcontractor_statements': SubcontractorStatement.objects.filter(status='submitted').count(),
        },
        'alerts': {
            'tasks_blocked': JobOrderDepartmentTask.objects.filter(status='blocked').count(),
            'ncrs_critical_open': NCR.objects.exclude(
                job_order__job_no='LEGACY-ARCHIVE'
            ).filter(
                severity='critical',
            ).exclude(status='closed').count(),
            'payments_overdue': PaymentSchedule.objects.filter(
                due_date__lt=today,
                is_paid=False,
            ).count(),
        },
    })


