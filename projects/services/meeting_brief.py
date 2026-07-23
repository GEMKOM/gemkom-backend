"""Meeting brief for the weekly review's Sunum Modu (meeting view).

One call per root job order. Aggregates, over the root's WHOLE subtree:
quality (NCR), revisions (technical drawings + target-date history),
procurement waiting items, CNC cuts waiting, machining operations/hours,
welding resource assignments, files by source, and — only for users with the
``view_job_costs`` role permission — a financial-health verdict with no
amounts.

Known gap: linear cutting is absent — LinearCuttingTask (the bar being cut)
carries no job_no, so a per-job "cuts waiting" cannot be derived for it.
"""

from decimal import Decimal

from django.db.models import (
    Count, DecimalField, ExpressionWrapper, F, FloatField, Prefetch, Q, Sum,
    Value,
)
from django.db.models.functions import Coalesce, NullIf

from .production_plan import _collect_subtree_nodes

# Financial verdict thresholds (share of selling price).
RISKY_COST_RATIO = Decimal('0.90')

NCR_OPEN_STATUSES = ('draft', 'submitted', 'rejected')  # models.py:1166 gate

FILES_PER_GROUP = 20


def _user_name(user):
    if user is None:
        return None
    full = (user.get_full_name() or '').strip()
    return full or user.username


def _file_entry(obj, request, job_no, size=None):
    try:
        url = request.build_absolute_uri(obj.file.url) if obj.file else None
    except Exception:
        url = None
    entry = {
        'id': obj.pk,
        'name': obj.name or getattr(obj, 'filename', '') or '',
        'url': url,
        'job_no': job_no,
        'uploaded_at': obj.uploaded_at,
        'uploaded_by_name': _user_name(obj.uploaded_by),
    }
    if size is not None:
        entry['size'] = size
    return entry


def _quality(job_nos):
    from quality_control.models import NCR

    severity_display = dict(NCR.SEVERITY_CHOICES)
    status_display = dict(NCR.STATUS_CHOICES)

    counts = NCR.objects.filter(job_order_id__in=job_nos).aggregate(
        total=Count('id'),
        open=Count('id', filter=Q(status__in=NCR_OPEN_STATUSES)),
        open_minor=Count('id', filter=Q(status__in=NCR_OPEN_STATUSES, severity='minor')),
        open_major=Count('id', filter=Q(status__in=NCR_OPEN_STATUSES, severity='major')),
        open_critical=Count('id', filter=Q(status__in=NCR_OPEN_STATUSES, severity='critical')),
    )

    open_list = [
        _ncr_entry(n, severity_display, status_display) for n in
        NCR.objects.filter(job_order_id__in=job_nos, status__in=NCR_OPEN_STATUSES)
        .order_by('-created_at')[:5]
    ]
    return {
        'total': counts['total'],
        'open': counts['open'],
        'open_by_severity': {
            'minor': counts['open_minor'],
            'major': counts['open_major'],
            'critical': counts['open_critical'],
        },
        'open_list': open_list,
    }


def _ncr_entry(n, severity_display, status_display):
    return {
        'ncr_number': n.ncr_number,
        'title': n.title,
        'severity': n.severity,
        'severity_display': severity_display.get(n.severity, n.severity),
        'status': n.status,
        'status_display': status_display.get(n.status, n.status),
        'job_no': n.job_order_id,
        'created_at': n.created_at,
    }


def _release_rows(job_nos, limit=None):
    """Newest technical-drawing release rows of any status, display-ready."""
    from projects.models import TechnicalDrawingRelease

    status_display = dict(TechnicalDrawingRelease.STATUS_CHOICES)
    rows = (
        TechnicalDrawingRelease.objects
        .filter(job_order_id__in=job_nos)
        .order_by('-released_at', '-pk')
        .values('revision_code', 'revision_number', 'status',
                'released_at', 'job_order_id')
    )
    if limit is not None:
        rows = rows[:limit]
    return [
        {
            'revision_code': r['revision_code'],
            'revision_number': r['revision_number'],
            'status': r['status'],
            'status_display': status_display.get(r['status'], r['status']),
            'released_at': r['released_at'],
            'job_no': r['job_order_id'],
        }
        for r in rows
    ]


def _revisions(root, job_nos):
    from projects.models import TechnicalDrawingRelease

    drawing_counts = TechnicalDrawingRelease.objects.filter(
        job_order_id__in=job_nos
    ).aggregate(
        superseded=Count('id', filter=Q(status='superseded')),
        in_revision=Count('id', filter=Q(status='in_revision')),
        total=Count('id'),
    )
    # Latest released drawing across the subtree. revision_number is only
    # unique per job, so recency (released_at) is the cross-job ordering.
    current = (
        TechnicalDrawingRelease.objects
        .filter(job_order_id__in=job_nos, status='released')
        .order_by('-released_at', '-pk')
        .values('revision_code', 'revision_number', 'released_at', 'job_order_id')
        .first()
    )

    # Newest release row of ANY status = "when was it last revised": a new
    # revision row is created at completion (released_at = creation time), so
    # recency moves when the revised drawing lands, not when it gets approved.
    latest = _release_rows(job_nos, limit=1)
    latest = latest[0] if latest else None

    target_revisions = list(
        root.target_date_revisions.select_related('changed_by')
        .order_by('-changed_at')[:3]
    )
    return {
        'drawing': {
            'revision_count': drawing_counts['superseded'],
            'in_revision_count': drawing_counts['in_revision'],
            'release_count': drawing_counts['total'],
            'current': current and {
                'revision_code': current['revision_code'],
                'revision_number': current['revision_number'],
                'released_at': current['released_at'],
                'job_no': current['job_order_id'],
            },
            'latest': latest,
        },
        'target_date': {
            'count': root.target_date_revisions.count(),
            'latest_list': [
                {
                    'previous_date': r.previous_date,
                    'new_date': r.new_date,
                    'reason': r.reason,
                    'changed_by_name': _user_name(r.changed_by),
                    'changed_at': r.changed_at,
                }
                for r in target_revisions
            ],
        },
    }


def _procurement(job_nos):
    """Waiting split by delivery + purchase-request coverage."""
    total = delivered = requested_waiting = not_yet_requested = 0
    for item in _procurement_rows(job_nos):
        total += 1
        if item['is_delivered']:
            delivered += 1
        elif item['requested_fully']:
            requested_waiting += 1
        else:
            not_yet_requested += 1
    return {
        'items_total': total,
        'items_delivered': delivered,
        'items_waiting': requested_waiting + not_yet_requested,
        'requested_waiting': requested_waiting,
        'not_yet_requested': not_yet_requested,
    }


def _procurement_rows(job_nos):
    """Purchaseable items with their PR-coverage flag resolved.

    ``quantity_remaining_for_purchase`` is deliberately avoided (per-item
    aggregate); and negating a status Q across the multi-valued reverse
    relation inside a filtered aggregate mis-groups — from the
    PurchaseRequestItem side the exclude is single-valued and unambiguous.
    """
    from planning.models import PlanningRequestItem
    from procurement.models import PurchaseRequestItem

    items = list(
        PlanningRequestItem.objects
        .filter(job_no__in=job_nos, quantity_to_purchase__gt=0)
        .values('id', 'is_delivered', 'quantity_to_purchase',
                'item__name', 'item__code', 'job_no')
    )
    requested = {
        row['planning_request_item_id']: row['qty'] or Decimal('0')
        for row in (
            PurchaseRequestItem.objects
            .filter(planning_request_item_id__in=[i['id'] for i in items])
            .exclude(purchase_request__status__in=('rejected', 'cancelled'))
            .values('planning_request_item_id')
            .annotate(qty=Sum('quantity'))
        )
    }
    for item in items:
        item['requested_fully'] = (
            requested.get(item['id'], Decimal('0')) >= item['quantity_to_purchase'])
    return items


def _cutting(job_nos):
    from cnc_cutting.models import CncPart

    # None and 0 both count as one part — parity with get_cnc_progress's
    # ``or 1`` (see production_plan._batched_domain_progress).
    qty_expr = Coalesce(NullIf(F('quantity'), Value(0)), Value(1))
    weight_expr = ExpressionWrapper(
        Coalesce(F('weight_kg'), Value(Decimal('0'))) * qty_expr,
        output_field=DecimalField(max_digits=16, decimal_places=3),
    )
    cut = Q(cnc_task__completion_date__isnull=False)
    # Uncut parts whose cut is tied to an undelivered plate stock line: the wait
    # belongs to procurement, not CNC. Parts on cuts without a planning-item
    # link stay plain "waiting".
    waiting_material = (
        Q(cnc_task__completion_date__isnull=True) &
        Q(cnc_task__planning_request_item__isnull=False) &
        Q(cnc_task__planning_request_item__is_delivered=False)
    )
    agg = CncPart.objects.filter(job_no__in=job_nos).aggregate(
        parts_total=Sum(qty_expr),
        parts_cut=Sum(qty_expr, filter=cut),
        weight_total=Sum(weight_expr),
        weight_cut=Sum(weight_expr, filter=cut),
        parts_waiting_material=Sum(qty_expr, filter=waiting_material),
        weight_waiting_material=Sum(weight_expr, filter=waiting_material),
    )
    parts_total = agg['parts_total'] or 0
    parts_cut = agg['parts_cut'] or 0
    weight_total = agg['weight_total'] or Decimal('0')
    weight_cut = agg['weight_cut'] or Decimal('0')

    return {
        'parts_total': parts_total,
        'parts_cut': parts_cut,
        'parts_waiting': parts_total - parts_cut,
        'weight_total': float(weight_total),
        'weight_cut': float(weight_cut),
        'weight_waiting': float(weight_total - weight_cut),
        'parts_waiting_material': agg['parts_waiting_material'] or 0,
        'weight_waiting_material': float(agg['weight_waiting_material'] or Decimal('0')),
    }


def _machining(job_nos):
    """Earned-hours math, parity with the batched machining progress branch:
    est<=0 skipped; completed ops earn full estimate; open ops earn
    min(spent/est, 1) * est."""
    from tasks.models import Part

    ops_total = ops_completed = 0
    est_total = spent_total = earned_total = 0.0
    for row in _machining_op_rows(job_nos):
        ops_total += 1
        completed = row['completion_date'] is not None
        if completed:
            ops_completed += 1
        estimated = float(row['estimated_hours'] or 0)
        spent = row['spent'] or 0.0
        spent_total += spent
        if estimated <= 0:
            continue
        est_total += estimated
        earned_total += estimated if completed else min(spent / estimated, 1.0) * estimated

    part_agg = Part.objects.filter(job_no__in=job_nos).aggregate(
        total=Count('key'),
        completed=Count('key', filter=Q(completion_date__isnull=False)),
    )
    return {
        'operations_total': ops_total,
        'operations_completed': ops_completed,
        'operations_waiting': ops_total - ops_completed,
        'estimated_hours_total': round(est_total, 1),
        'hours_spent': round(spent_total, 1),
        'hours_earned': round(earned_total, 1),
        'hours_remaining': round(max(est_total - earned_total, 0.0), 1),
        'parts_total': part_agg['total'],
        'parts_completed': part_agg['completed'],
    }


def _machining_op_rows(job_nos):
    """Per-operation rows with timer-spent hours annotated (one query)."""
    from tasks.models import Operation

    return list(
        Operation.objects.filter(part__job_no__in=job_nos)
        .values('key', 'name', 'part__name', 'part__job_no',
                'estimated_hours', 'completion_date')
        .annotate(
            spent=Coalesce(
                ExpressionWrapper(
                    Sum('timers__finish_time', filter=Q(timers__finish_time__isnull=False)) -
                    Sum('timers__start_time', filter=Q(timers__finish_time__isnull=False)),
                    output_field=FloatField(),
                ) / 3600000.0,
                Value(0.0),
            )
        )
    )


def _welding(job_nos):
    """Who is welding and how far along — committed assignments (subcontractor
    or internal team) plus not-yet-promoted capacity plans."""
    from subcontracting.models import SubcontractingAssignment
    from welding.models import (
        InternalTeamAssignment, WeldingPlanAllocation, WeldingTimeEntry,
    )
    from projects.models import JobOrderDepartmentTask

    welding_task = (
        Q(department_task__task_type='welding')
        | Q(department_task__parent__task_type='welding')
    )
    # The skip-path of get_completion_percentage checks prefetched subtasks;
    # without the prefetch every progress read fires a count aggregate.
    task_qs = JobOrderDepartmentTask.objects.prefetch_related('subtasks')

    rows = []

    subcontracted = (
        SubcontractingAssignment.objects
        .filter(welding_task, department_task__job_order_id__in=job_nos, is_retired=False)
        .exclude(price_tier__tier_type='paint')
        .select_related('subcontractor')
        .prefetch_related(Prefetch('department_task', queryset=task_qs))
    )
    for a in subcontracted:
        rows.append({
            'name': a.subcontractor.name,
            'kind': 'subcontractor',
            'job_no': a.department_task.job_order_id,
            'allocated_weight_kg': float(a.allocated_weight_kg),
            'progress_pct': float(a.current_progress),
            'planned': False,
        })

    internal = (
        InternalTeamAssignment.objects
        .filter(welding_task, department_task__job_order_id__in=job_nos)
        .select_related('team')
        .prefetch_related(Prefetch('department_task', queryset=task_qs))
    )
    for a in internal:
        rows.append({
            'name': a.team.name,
            'kind': 'team',
            'job_no': a.department_task.job_order_id,
            'allocated_weight_kg': float(a.allocated_weight_kg),
            'progress_pct': float(a.current_progress),
            'planned': False,
        })

    planned = (
        WeldingPlanAllocation.objects
        .filter(
            department_task__job_order_id__in=job_nos,
            promoted_subcontracting_assignment__isnull=True,
            promoted_internal_team_assignment__isnull=True,
        )
        .select_related('subcontractor', 'team', 'department_task')
    )
    for p in planned:
        rows.append({
            'name': p.subcontractor.name if p.subcontractor_id else p.team.name,
            'kind': 'subcontractor' if p.subcontractor_id else 'team',
            'job_no': p.department_task.job_order_id,
            'allocated_weight_kg': float(p.allocated_weight_kg),
            'progress_pct': None,
            'planned': True,
            'planned_start_date': p.planned_start_date,
            'planned_end_date': p.planned_end_date,
        })

    committed = [r for r in rows if not r['planned']]
    kg_total = sum(r['allocated_weight_kg'] for r in committed)
    weighted = (
        round(sum(r['allocated_weight_kg'] * r['progress_pct'] for r in committed) / kg_total, 1)
        if kg_total else None
    )
    rows.sort(key=lambda r: (r['planned'], -r['allocated_weight_kg']))

    return {
        'resources': rows,
        'resources_total': len(rows),
        'allocated_kg_total': round(sum(r['allocated_weight_kg'] for r in rows), 2),
        'weighted_progress_pct': weighted,
        'task_progress_pct': _welding_task_progress(job_nos),
        'hours': _welding_hours(job_nos, WeldingTimeEntry),
    }


def _welding_task_progress(job_nos):
    """Weighted welding-task progress — the "no kg assigned yet but the
    welder logged 90%" signal. Exact mirror of the model's full progress path
    (projects/models.py get_completion_percentage): completed→100;
    pending/blocked→0 BEFORE any subtask fallthrough; a task with subtasks
    rolls up over them excluding skipped+cancelled (all-excluded → 0);
    otherwise manual_progress; everything but completed capped at 99.
    """
    from projects.models import JobOrderDepartmentTask

    tasks = list(
        JobOrderDepartmentTask.objects
        .filter(task_type='welding', job_order_id__in=job_nos)
        .exclude(status__in=('cancelled', 'skipped'))
        .values('id', 'parent_id', 'status', 'manual_progress', 'weight')
    )
    if not tasks:
        return None
    # A welding-typed subtask under a welding-typed main is already inside
    # its parent's rollup — keep only the top of each selected chain.
    selected_ids = {t['id'] for t in tasks}
    tasks = [t for t in tasks if t['parent_id'] not in selected_ids]

    subtasks = {}
    for row in (
        JobOrderDepartmentTask.objects
        .filter(parent_id__in=[t['id'] for t in tasks])
        .values('parent_id', 'status', 'manual_progress', 'weight')
    ):
        subtasks.setdefault(row['parent_id'], []).append(row)

    ninety_nine = Decimal('99')

    def leaf_pct(status, manual):
        if status == 'completed':
            return Decimal('100')
        if status in ('pending', 'blocked'):
            return Decimal('0')
        return min(Decimal(str(manual or 0)), ninety_nine)

    weight_sum = Decimal('0')
    earned_sum = Decimal('0')
    for t in tasks:
        if t['status'] == 'completed':
            pct = Decimal('100')
        elif t['status'] in ('pending', 'blocked'):
            pct = Decimal('0')
        else:
            children = subtasks.get(t['id'], [])
            counted = [s for s in children if s['status'] not in ('skipped', 'cancelled')]
            if children:
                total_w = sum(Decimal(str(s['weight'])) for s in counted)
                if total_w > 0:
                    earned = sum(
                        leaf_pct(s['status'], s['manual_progress']) / 100 * Decimal(str(s['weight']))
                        for s in counted
                    )
                    pct = min(earned / total_w * 100, ninety_nine)
                else:
                    pct = Decimal('0')
            else:
                pct = leaf_pct(t['status'], t['manual_progress'])
        weight = Decimal(str(t['weight'] or 1))
        weight_sum += weight
        earned_sum += weight * pct

    return float(round(earned_sum / weight_sum, 1)) if weight_sum else None


def _welding_hours(job_nos, WeldingTimeEntry):
    """Man-hours from welding time entries, overtime buckets separated.
    One filtered aggregate, no join (this model has no status field — the
    rejected-entries invariant belongs to the overtime app)."""
    agg = WeldingTimeEntry.objects.filter(job_no__in=job_nos).aggregate(
        regular=Sum('hours', filter=Q(overtime_type='regular')),
        after_hours=Sum('hours', filter=Q(overtime_type='after_hours')),
        holiday=Sum('hours', filter=Q(overtime_type='holiday')),
        total=Sum('hours'),
    )
    return {key: float(value or 0) for key, value in agg.items()}


def _files(job_nos, request):
    """Grouped file listing. Sales-offer documents are deliberately excluded
    (user decision). file_size is omitted for the storage-backed models: the
    property does a storage HEAD per file, which on S3-compatible storage
    means one network round-trip each."""
    from projects.models import (
        DiscussionAttachment, JobOrderDepartmentTaskFile, JobOrderFile,
    )

    groups = {}

    jo_qs = JobOrderFile.objects.filter(job_order_id__in=job_nos).select_related('uploaded_by')
    groups['job_order'] = {
        'total': jo_qs.count(),
        'items': [
            _file_entry(f, request, f.job_order_id)
            for f in jo_qs.order_by('-uploaded_at')[:FILES_PER_GROUP]
        ],
    }

    task_qs = (
        JobOrderDepartmentTaskFile.objects
        .filter(task__job_order_id__in=job_nos)
        .select_related('uploaded_by', 'task')
    )
    groups['task'] = {
        'total': task_qs.count(),
        'items': [
            _file_entry(f, request, f.task.job_order_id)
            for f in task_qs.order_by('-uploaded_at')[:FILES_PER_GROUP]
        ],
    }

    in_subtree = (
        Q(topic__job_order_id__in=job_nos)
        | Q(comment__topic__job_order_id__in=job_nos)
    )
    disc_qs = (
        DiscussionAttachment.objects.filter(in_subtree)
        .select_related('uploaded_by', 'topic', 'comment__topic')
    )
    groups['discussion'] = {
        'total': disc_qs.count(),
        'items': [
            _file_entry(
                f, request,
                (f.topic or f.comment.topic).job_order_id if (f.topic_id or f.comment_id) else None,
                size=f.size,
            )
            for f in disc_qs.order_by('-uploaded_at')[:FILES_PER_GROUP]
        ],
    }
    return groups


def _delivered_uncosted_material(job_nos):
    """Offer/historical-priced material sitting in the estimate for DELIVERED
    items with no real cost (no saved procurement line, no actual PO price).

    A delivered item has no purchase left to happen, so that portion of the
    estimate is fiction the actuals can never catch up to (typically stock
    material). The stored estimate itself stays untouched (user decision) —
    the meeting verdict alone subtracts this before comparing against price.
    """
    from planning.price_utils import resolve_planning_item_price
    from projects.models import JobOrderProcurementLine
    from projects.services.costing import _planning_items_with_price_annotations

    covered = set(
        JobOrderProcurementLine.objects
        .filter(job_order_id__in=job_nos, planning_request_item__isnull=False)
        .values_list('planning_request_item_id', flat=True)
    )
    total = Decimal('0')
    for pri in _planning_items_with_price_annotations(list(job_nos)).filter(is_delivered=True):
        if pri.pk in covered:
            continue
        price = resolve_planning_item_price(pri)
        if not price or price['price_source'] == 'po_line':
            continue
        total += Decimal(str(pri.quantity or 0)) * price['unit_price_eur']
    return total


def _financial(root, job_nos):
    """Traffic-light verdict, no amounts. Compares the PROJECTED full cost
    (max of actuals and the cached 100%-projection, which is built on top of
    actuals — so max, never sum) against the effective selling price.
    Progress-vs-spend is deliberately not used: procurement front-loads cost
    and would flag every early-stage job.

    Never recomputes cost summaries here — recompute writes rows and chains
    up the parent tree, which a GET must not do.
    """
    from projects.models import JobOrderCostSummary
    from projects.services.selling_price import DerivedSellingPriceResolver

    try:
        summary = root.cost_summary
    except JobOrderCostSummary.DoesNotExist:
        summary = None

    actual = Decimal(str(summary.actual_total_cost or 0)) if summary else Decimal('0')
    estimated = Decimal(str(summary.estimated_total_cost or 0)) if summary else Decimal('0')

    if summary is None or (actual <= 0 and estimated <= 0):
        return {'verdict': 'no_data', 'reason': 'Maliyet özeti henüz oluşturulmamış.',
                'price_is_derived': False}

    price_info = DerivedSellingPriceResolver([root.job_no]).display_for(root.job_no)
    price = Decimal(str(price_info['amount_eur'] or 0))
    derived = bool(price_info['is_derived'])

    if price_info['source'] == 'none' or price <= 0:
        return {'verdict': 'no_price',
                'reason': 'Satış fiyatı girilmemiş; türetilebilir fiyat da yok.',
                'price_is_derived': False}

    # The verdict compares the PROJECTED cost against price. Estimated
    # portions already realised cheaper are replaced by reality: fictional
    # offer prices for delivered-but-uncosted items are subtracted first.
    estimated_adjusted = estimated
    if estimated > 0:
        estimated_adjusted = max(
            Decimal('0'), estimated - _delivered_uncosted_material(job_nos))
    cost_projected = max(actual, estimated_adjusted)
    result = {'price_is_derived': derived}
    if actual >= price:
        result.update(verdict='critical',
                      reason='Gerçekleşen maliyet satış fiyatına ulaştı veya aştı.')
    elif cost_projected > price:
        result.update(verdict='critical',
                      reason='Öngörülen toplam maliyet satış fiyatını aşıyor.')
    elif cost_projected > RISKY_COST_RATIO * price:
        result.update(verdict='risky',
                      reason='Öngörülen toplam maliyet satış fiyatının %90 sınırını aştı.')
    elif estimated > 0 and actual > estimated:
        result.update(verdict='risky',
                      reason='Gerçekleşen maliyet tahmini toplam maliyeti aştı (bütçe aşımı eğilimi).')
    else:
        result.update(verdict='healthy',
                      reason='Maliyet ile satış fiyatı dengesi sağlıklı görünüyor.')
    return result


# ---------------------------------------------------------------------------
# On-demand section details — fetched only when a card's modal opens, so the
# main brief stays light (a subtree can hold hundreds of items/operations).
# ---------------------------------------------------------------------------

def _machining_detail(root, job_nos):
    """Every operation in the subtree, open work first."""
    operations = []
    for row in _machining_op_rows(job_nos):
        estimated = float(row['estimated_hours'] or 0)
        operations.append({
            'key': row['key'],
            'name': row['name'],
            'part_name': row['part__name'],
            'job_no': row['part__job_no'],
            'estimated_hours': round(estimated, 1),
            'hours_spent': round(row['spent'] or 0.0, 1),
            'completed': row['completion_date'] is not None,
        })
    # Open work first, biggest estimates up top — the modal's reading order.
    operations.sort(key=lambda o: (o['completed'], -o['estimated_hours']))
    return {'operations': operations}


def _cutting_detail(root, job_nos):
    """Every CNC part in the subtree with its cut state, uncut first."""
    from cnc_cutting.models import CncPart

    parts = [
        {
            'image_no': row['image_no'],
            'position_no': row['position_no'],
            'job_no': row['job_no'],
            'nesting': row['cnc_task_id'],
            'quantity': row['quantity'] or 1,
            'weight_kg': float(row['weight_kg'] or 0),
            'cut': row['cnc_task__completion_date'] is not None,
            'material_pending': (
                row['cnc_task__completion_date'] is None
                and row['cnc_task__planning_request_item'] is not None
                and row['cnc_task__planning_request_item__is_delivered'] is False
            ),
            'plate_item_code': row['cnc_task__planning_request_item__item__code'],
        }
        for row in (
            CncPart.objects
            .filter(job_no__in=job_nos)
            .values('image_no', 'position_no', 'job_no', 'cnc_task_id',
                    'quantity', 'weight_kg', 'cnc_task__completion_date',
                    'cnc_task__planning_request_item',
                    'cnc_task__planning_request_item__is_delivered',
                    'cnc_task__planning_request_item__item__code')
        )
    ]
    parts.sort(key=lambda p: (p['cut'], -p['weight_kg']))
    return {'parts': parts}


def _quality_detail(root, job_nos):
    """Every NCR in the subtree, newest first, all statuses."""
    from quality_control.models import NCR

    severity_display = dict(NCR.SEVERITY_CHOICES)
    status_display = dict(NCR.STATUS_CHOICES)
    return {'list': [
        _ncr_entry(n, severity_display, status_display) for n in
        NCR.objects.filter(job_order_id__in=job_nos).order_by('-created_at')
    ]}


def _procurement_detail(root, job_nos):
    """Every purchaseable item in the subtree — blockers, in-request and
    delivered alike."""
    items = [
        {
            'item_name': item['item__name'],
            'item_code': item['item__code'],
            'job_no': item['job_no'],
            'quantity_to_purchase': float(item['quantity_to_purchase']),
            'stage': ('delivered' if item['is_delivered']
                      else 'requested' if item['requested_fully']
                      else 'not_requested'),
        }
        for item in _procurement_rows(job_nos)
    ]
    # Blockers first, then in-request, delivered last; big quantities up top.
    stage_order = {'not_requested': 0, 'requested': 1, 'delivered': 2}
    items.sort(key=lambda w: (stage_order[w['stage']], -w['quantity_to_purchase']))
    return {'items': items}


def _revisions_detail(root, job_nos):
    """Every drawing release and every target-date change."""
    return {
        'releases': _release_rows(job_nos, limit=None),
        'target_date_revisions': [
            {
                'previous_date': r.previous_date,
                'new_date': r.new_date,
                'reason': r.reason,
                'changed_by_name': _user_name(r.changed_by),
                'changed_at': r.changed_at,
            }
            for r in root.target_date_revisions.select_related('changed_by')
            .order_by('-changed_at')
        ],
    }


MEETING_BRIEF_SECTIONS = {
    'machining': _machining_detail,
    'cutting': _cutting_detail,
    'quality': _quality_detail,
    'procurement': _procurement_detail,
    'revisions': _revisions_detail,
}


def build_meeting_brief_section(root, section):
    nodes = _collect_subtree_nodes(root)
    job_nos = [n['job_no'] for n in nodes]
    return MEETING_BRIEF_SECTIONS[section](root, job_nos)


def build_meeting_brief(root, request, include_financial):
    nodes = _collect_subtree_nodes(root)
    job_nos = [n['job_no'] for n in nodes]

    brief = {
        'job_no': root.job_no,
        'node_count': len(job_nos),
        'quality': _quality(job_nos),
        'revisions': _revisions(root, job_nos),
        'procurement': _procurement(job_nos),
        'cutting': _cutting(job_nos),
        'machining': _machining(job_nos),
        'welding': _welding(job_nos),
        'files': _files(job_nos, request),
    }
    if include_financial:
        brief['financial'] = _financial(root, job_nos)
    return brief
