"""
Full-subtree production plan for a job order.

Builds the payload for ``GET /projects/job-orders/{job_no}/production-plan/``:
every department task (main tasks + subtasks) of the job order and all of its
descendant job orders — including phase nodes and allocations — with planned
vs. actual dates, working-day lateness, a progress-aware schedule forecast,
and per-node / overall rollups.

Lateness (backward-looking): end/start variance for completed tasks, overdue
working days for open tasks past their target.

Forecast (forward-looking, read-only overlay — target dates are never
modified):
* Started tasks project their end from the observed work rate
  (elapsed working days / progress).
* Not-yet-started tasks are re-anchored to max(today, target start, and the
  projected end of their predecessors) — explicit ``depends_on`` edges where
  present, otherwise the previous main task by ``sequence`` within the same
  job order. A predecessor that binds the start marks the task as pushed
  (``pushed_by``).
* Open tasks projected to finish after their target are classified
  ``at_risk``.

Read-only. Query cost stays bounded: one JobOrder query per depth level, one
for phased-master detection, one for all tasks (+2 prefetches), one for the
holiday calendar, plus the real-progress lookups for currently OPEN
CNC/machining/procurement tasks (a handful per tree; completed ones are 100%
by definition and use the cheap path).
"""
import re
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from projects.models import JobOrder, JobOrderDepartmentTask
from projects.services.schedule import (
    ZERO,
    add_working_days,
    load_holiday_calendar,
    local_date,
    next_working_day,
    span_end,
    today_local,
    working_day_delta,
    working_days_inclusive,
)

_JOB_STATUS_DISPLAY = dict(JobOrder.STATUS_CHOICES)

_NODE_VALUES = (
    'job_no', 'parent_id', 'title', 'status', 'completion_percentage',
    'target_completion_date', 'quantity', 'phase_number', 'source_job_order_id',
)

CLASSIFICATION_KEYS = (
    'completed_on_time', 'completed_late', 'overdue', 'at_risk',
    'in_progress', 'not_started', 'unplanned', 'excluded',
)

# Safety caps for the forecast walk
MAX_REMAINING_WD = Decimal('260')      # ~a working year
DEFAULT_DURATION_WD = Decimal('1')     # tasks without a planned window
CALENDAR_LOOKAHEAD_DAYS = 400          # holidays loaded this far past today

OPEN_STATUSES = ('pending', 'blocked', 'in_progress', 'on_hold')


def _job_no_sort_key(job_no):
    """Order siblings: plain jobs (product masters etc.) first by job_no,
    then phase nodes/allocations by numeric phase number (P10 after P2)."""
    if '/P' in job_no:
        base, _, phase = job_no.rpartition('/P')
        try:
            return (1, base, int(phase))
        except ValueError:
            return (1, base, 0)
    return (0, job_no, 0)


def _collect_subtree_nodes(root):
    """BFS on the parent FK (one query per depth level), then DFS-order.

    job_no__startswith would be wrong here: "254-1" prefixes "254-10", and
    phase allocations ("270-01-01/P1") live under the phase node ("270-01/P1")
    whose prefix they do not share. The FK walk is the source of truth.
    """
    rows = {
        root.job_no: {
            'job_no': root.job_no,
            'parent_id': None,  # subtree root: parent (if any) is out of scope
            'title': root.title,
            'status': root.status,
            'completion_percentage': root.completion_percentage,
            'target_completion_date': root.target_completion_date,
            'quantity': root.quantity,
            'phase_number': root.phase_number,
            'source_job_order_id': root.source_job_order_id,
        }
    }
    children_map = defaultdict(list)
    frontier = [root.job_no]
    while frontier:
        child_rows = JobOrder.objects.filter(parent_id__in=frontier).values(*_NODE_VALUES)
        frontier = []
        for row in child_rows:
            if row['job_no'] in rows:  # guard against a malformed cycle
                continue
            rows[row['job_no']] = row
            children_map[row['parent_id']].append(row['job_no'])
            frontier.append(row['job_no'])

    # Which of these jobs have phase mirrors anywhere (phased engineering masters)?
    mirror_sources = set(
        JobOrder.objects.filter(source_job_order_id__in=rows.keys())
        .values_list('source_job_order_id', flat=True)
    )

    ordered = []

    def visit(job_no, depth):
        row = rows[job_no]
        ordered.append({
            'job_no': job_no,
            'parent': row['parent_id'],
            'depth': depth,
            'title': row['title'],
            'status': row['status'],
            'status_display': _JOB_STATUS_DISPLAY.get(row['status'], row['status']),
            'completion_percentage': float(row['completion_percentage']),
            'target_completion_date': row['target_completion_date'],
            'quantity': row['quantity'],
            'is_phase_job': row['source_job_order_id'] is not None,
            'phase_number': row['phase_number'],
            'is_phased_master': job_no in mirror_sources,
        })
        for child in sorted(children_map.get(job_no, []), key=_job_no_sort_key):
            visit(child, depth + 1)

    visit(root.job_no, 0)
    return ordered


def _fetch_tasks(job_nos):
    """All department tasks (mains + subtasks) of the given jobs, one query."""
    return list(
        JobOrderDepartmentTask.objects.filter(job_order_id__in=job_nos)
        .select_related('assigned_to', 'job_order')
        .prefetch_related('subtasks', 'depends_on')
        .order_by('job_order_id', 'sequence', 'id')
    )


def _ordered_tasks(job_tasks):
    """Main tasks by sequence, each immediately followed by its subtasks."""
    subs_by_parent = defaultdict(list)
    for task in job_tasks:
        if task.parent_id is not None:
            subs_by_parent[task.parent_id].append(task)

    ordered, emitted = [], set()
    for task in job_tasks:
        if task.parent_id is None:
            ordered.append(task)
            emitted.add(task.id)
            for sub in subs_by_parent.get(task.id, ()):
                ordered.append(sub)
                emitted.add(sub.id)
    # Orphan subtasks (parent on another job order — shouldn't happen): keep visible.
    ordered.extend(t for t in job_tasks if t.id not in emitted)
    return ordered


def _is_special_task(task):
    """CNC / machining / procurement tasks compute progress from their own
    domain data (parts, operations, purchase items)."""
    return (
        task.task_type in ('cnc_cutting', 'machining')
        or task.title in ('CNC Kesim', 'Talaşlı İmalat')
        or task.department == 'procurement'
    )


def _task_domain(task):
    """Which first-progress evidence stream applies to this task, if any."""
    if task.task_type == 'cnc_cutting' or task.title == 'CNC Kesim':
        return 'cnc'
    if task.task_type == 'machining' or task.title == 'Talaşlı İmalat':
        return 'machining'
    if task.task_type == 'welding' or task.title == 'Kaynaklı İmalat':
        return 'welding'
    if task.department == 'procurement':
        return 'procurement'
    if task.department == 'design':
        return 'design'
    return None


def _ms_to_local_date(ms):
    from datetime import datetime, timezone as dt_timezone
    if not ms:
        return None
    return local_date(datetime.fromtimestamp(ms / 1000, tz=dt_timezone.utc))


def _first_progress_evidence(job_nos):
    """Earliest real work evidence per job, per domain — one query each.

    ``started_at`` is stamped by the dependency auto-start (often the day the
    task tree was created), so "Gerçek Başlangıç" prefers actual activity:
    first machining timer, first cut CNC part, first welding time entry,
    first purchase request, first drawing release.
    """
    from django.db.models import Min

    evidence = {key: {} for key in ('cnc', 'machining', 'welding', 'procurement', 'design')}
    if not job_nos:
        return evidence

    from cnc_cutting.models import CncPart
    for row in (CncPart.objects
                .filter(job_no__in=job_nos, cnc_task__completion_date__isnull=False)
                .values('job_no').annotate(first=Min('cnc_task__completion_date'))):
        evidence['cnc'][row['job_no']] = _ms_to_local_date(row['first'])

    from tasks.models import Operation
    for row in (Operation.objects
                .filter(part__job_no__in=job_nos, timers__start_time__isnull=False)
                .values('part__job_no').annotate(first=Min('timers__start_time'))):
        evidence['machining'][row['part__job_no']] = _ms_to_local_date(row['first'])

    from welding.models import WeldingTimeEntry
    for row in (WeldingTimeEntry.objects
                .filter(job_no__in=job_nos)
                .values('job_no').annotate(first=Min('date'))):
        evidence['welding'][row['job_no']] = row['first']

    from procurement.models import PurchaseRequestItem
    for row in (PurchaseRequestItem.objects
                .filter(planning_request_item__job_no__in=job_nos)
                .values('planning_request_item__job_no')
                .annotate(first=Min('purchase_request__created_at'))):
        evidence['procurement'][row['planning_request_item__job_no']] = local_date(row['first'])

    from projects.models import TechnicalDrawingRelease
    for row in (TechnicalDrawingRelease.objects
                .filter(job_order_id__in=job_nos)
                .values('job_order_id').annotate(first=Min('released_at'))):
        evidence['design'][row['job_order_id']] = local_date(row['first'])

    return evidence


def _effective_start_map(tasks, evidence):
    """Evidence-based first-progress date per task id (None when no evidence).

    Main tasks additionally inherit the earliest evidence of their subtasks —
    evidence only, never a subtask's auto-stamped ``started_at``.
    """
    own = {}
    for task in tasks:
        domain = _task_domain(task)
        date = evidence.get(domain, {}).get(task.job_order_id) if domain else None
        own[task.id] = date

    child_min = defaultdict(lambda: None)
    for task in tasks:
        if task.parent_id is not None and own[task.id] is not None:
            current = child_min[task.parent_id]
            if current is None or own[task.id] < current:
                child_min[task.parent_id] = own[task.id]

    effective = {}
    for task in tasks:
        candidates = [d for d in (own[task.id], child_min.get(task.id)) if d is not None]
        effective[task.id] = min(candidates) if candidates else None
    return effective


def _batched_domain_progress(job_nos):
    """(earned, total) per job for the three special domains, in a fixed
    number of queries regardless of job count — the per-task
    ``get_completion_percentage(skip_expensive_calculations=False)`` path is
    N+1 and unusable at portfolio scale.
    """
    domains = {'cnc': {}, 'machining': {}, 'procurement': {}}
    if not job_nos:
        return domains

    from django.db.models import (
        DecimalField, ExpressionWrapper, F, FloatField, Prefetch, Q, Sum, Value,
    )
    from django.db.models.functions import Coalesce, NullIf

    # CNC: weight-based part completion — parity with get_cnc_progress:
    # (weight_kg or 0) * (quantity or 1) — note ``or 1`` maps BOTH None and 0
    # to 1, hence NullIf before Coalesce; earned when the CncTask finished.
    from cnc_cutting.models import CncPart
    weight_expr = ExpressionWrapper(
        Coalesce(F('weight_kg'), Value(Decimal('0'))) *
        Coalesce(NullIf(F('quantity'), Value(0)), Value(1)),
        output_field=DecimalField(max_digits=16, decimal_places=3),
    )
    for row in (
        CncPart.objects.filter(job_no__in=job_nos)
        .values('job_no')
        .annotate(
            total=Sum(weight_expr),
            earned=Sum(weight_expr, filter=Q(cnc_task__completion_date__isnull=False)),
        )
    ):
        domains['cnc'][row['job_no']] = (
            row['earned'] or Decimal('0'), row['total'] or Decimal('0'))

    # Machining: per-operation timer hours vs estimate — parity with
    # get_machining_progress (skip est<=0; completed ops earn full credit;
    # otherwise min(spent/est, 1) * est; all timer types counted).
    from tasks.models import Operation
    op_rows = (
        Operation.objects.filter(part__job_no__in=job_nos)
        .values('part__job_no', 'key', 'estimated_hours', 'completion_date')
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
    machining_acc = defaultdict(lambda: [0.0, 0.0])  # job -> [earned, total]
    for row in op_rows:
        estimated = float(row['estimated_hours'] or 0)
        if estimated <= 0:
            continue
        acc = machining_acc[row['part__job_no']]
        acc[1] += estimated
        if row['completion_date'] is not None:
            acc[0] += estimated
        else:
            acc[0] += min((row['spent'] or 0.0) / estimated, 1.0) * estimated
    for job_no, (earned, total) in machining_acc.items():
        domains['machining'][job_no] = (
            Decimal(str(round(earned, 4))), Decimal(str(round(total, 4))))

    # Procurement: per-item stage logic (Python, not expressible as one
    # aggregate) over a fully prefetched queryset — the refactored
    # PlanningRequestItem.get_procurement_progress consumes these caches, so
    # the whole batch costs a fixed ~7 queries.
    from planning.models import PlanningRequestItem
    from procurement.models import PurchaseRequestItem
    items = (
        PlanningRequestItem.objects
        .filter(job_no__in=job_nos, quantity_to_purchase__gt=0)
        .select_related('item')
        .prefetch_related(Prefetch(
            'purchase_request_items',
            queryset=PurchaseRequestItem.objects
            .select_related('purchase_request')
            .prefetch_related('po_lines__po', 'offers__supplier_offer__supplier'),
        ))
    )
    for item in items:
        earned, total = item.get_procurement_progress()
        current = domains['procurement'].get(item.job_no, (Decimal('0'), Decimal('0')))
        domains['procurement'][item.job_no] = (current[0] + earned, current[1] + total)

    return domains


def _material_wait_map(job_nos):
    """Per-job CNC material-wait signal, in two fixed queries: open cuts whose
    linked plate stock line (PlanningRequestItem) has not been delivered, plus
    undelivered plate items for the job regardless of cuts (material missing,
    cuts not even created yet). Jobs with neither signal are absent from the map,
    so callers can attach ``map.get(job_no)`` directly (None = no wait)."""
    result = {}
    if not job_nos:
        return result

    from django.db.models import Count, Q
    from cnc_cutting.models import CncPart, PLATE_ITEM_CODE_PREFIXES
    from planning.models import PlanningRequestItem

    for row in (
        CncPart.objects
        .filter(
            job_no__in=job_nos,
            cnc_task__completion_date__isnull=True,
            cnc_task__planning_request_item__isnull=False,
            cnc_task__planning_request_item__is_delivered=False,
        )
        .values('job_no')
        .annotate(cuts=Count('cnc_task_id', distinct=True))
    ):
        result[row['job_no']] = {'cuts_waiting': row['cuts'], 'plate_items_pending': 0}

    plate_q = Q()
    for prefix in PLATE_ITEM_CODE_PREFIXES:
        plate_q |= Q(item__code__startswith=prefix)
    for row in (
        PlanningRequestItem.objects
        .filter(plate_q, job_no__in=job_nos, is_delivered=False, quantity_to_purchase__gt=0)
        .values('job_no')
        .annotate(items=Count('id'))
    ):
        entry = result.setdefault(row['job_no'], {'cuts_waiting': 0, 'plate_items_pending': 0})
        entry['plate_items_pending'] = row['items']

    return result


_MAX_IN_PROGRESS = Decimal('99.00')


def _full_path_open_progress(task, domains, progress):
    """The skip_expensive_calculations=False fallthrough for an open special
    task whose domain has no data (procurement with no purchaseable items) —
    mirrors models.py:1586 + 1624-1650: pending/blocked are 0; otherwise
    weight-weighted subtask progress (skipped AND cancelled excluded, partial
    credit) or manual_progress, capped at 99."""
    if task.status in ('pending', 'blocked'):
        return Decimal('0.00')
    subtasks = list(task.subtasks.all())  # prefetched by _fetch_tasks
    if subtasks:
        total_weight = Decimal('0.00')
        earned_weight = Decimal('0.00')
        for subtask in subtasks:
            if subtask.status in ('skipped', 'cancelled'):
                continue
            weight = Decimal(str(subtask.weight))
            total_weight += weight
            sub_pct = progress.get(subtask.id)
            if sub_pct is None:
                sub_pct = (
                    _progress_from_domains(subtask, domains, progress)
                    if subtask.status in OPEN_STATUSES and _is_special_task(subtask)
                    else subtask.get_completion_percentage(skip_expensive_calculations=True)
                )
            earned_weight += (Decimal(str(sub_pct)) / 100) * weight
        if total_weight > 0:
            pct = ((earned_weight / total_weight) * 100).quantize(Decimal('0.01'))
            return min(pct, _MAX_IN_PROGRESS)
        return Decimal('0.00')
    return min(task.manual_progress, _MAX_IN_PROGRESS)


def _progress_from_domains(task, domains, progress):
    """Percentage for an OPEN special task from the batched domain data —
    branch-for-branch parity with get_completion_percentage(False)."""
    is_cnc = task.task_type == 'cnc_cutting' or task.title == 'CNC Kesim'
    is_machining = task.task_type == 'machining' or task.title == 'Talaşlı İmalat'

    if is_cnc or is_machining:
        earned, total = domains['cnc' if is_cnc else 'machining'].get(
            task.job_order_id, (Decimal('0'), Decimal('0')))
        if total > 0:
            return min(((earned / total) * 100).quantize(Decimal('0.01')), _MAX_IN_PROGRESS)
        return Decimal('0.00')

    # Procurement: no purchaseable items -> the model falls through to the
    # full manual/subtask path (NOT zero, and NOT the flat-50 skip path).
    earned, total = domains['procurement'].get(
        task.job_order_id, (Decimal('0'), Decimal('0')))
    if total > 0:
        return min(((earned / total) * 100).quantize(Decimal('0.01')), _MAX_IN_PROGRESS)
    return _full_path_open_progress(task, domains, progress)


def _compute_progress_map(tasks, domains=None):
    """Real completion percentage per task id.

    Open special tasks read the batched domain aggregates (real progress at a
    fixed query cost); everything else uses the cheap prefetch-aware path.
    Two passes so a special task's subtask-based fallthrough can reuse the
    already-computed subtask percentages.
    """
    if domains is None:
        special_jobs = sorted({
            task.job_order_id for task in tasks
            if task.status in OPEN_STATUSES and _is_special_task(task)
        })
        domains = _batched_domain_progress(special_jobs)

    progress = {}
    special_open = []
    for task in tasks:
        if task.status in OPEN_STATUSES and _is_special_task(task):
            special_open.append(task)
        else:
            progress[task.id] = task.get_completion_percentage(
                skip_expensive_calculations=True)
    for task in special_open:
        progress[task.id] = _progress_from_domains(task, domains, progress)
    return progress


def _build_calendar(tasks, today):
    """One holiday query spanning every date the lateness AND forecast math
    can touch (projections walk into the future)."""
    dates = []
    for task in tasks:
        for d in (
            task.target_start_date,
            task.target_completion_date,
            local_date(task.started_at),
            local_date(task.completed_at),
        ):
            if d is not None:
                dates.append(d)
    if not dates:
        return {}
    dates.append(today)
    from datetime import timedelta
    return load_holiday_calendar(min(dates), max(dates) + timedelta(days=CALENDAR_LOOKAHEAD_DAYS))


def _classify(status, target_end, end_variance, overdue):
    if status in ('cancelled', 'skipped'):
        return 'excluded'
    if target_end is None:
        return 'unplanned'
    if status == 'completed':
        if end_variance is not None and end_variance > 0:
            return 'completed_late'
        return 'completed_on_time'
    if overdue is not None:  # only set when > 0 working days past target
        return 'overdue'
    if status in ('in_progress', 'on_hold'):
        return 'in_progress'
    return 'not_started'  # pending / blocked


def _task_dict(task, calendar, today, completion_percentage, effective_start=None,
               material_wait=None):
    # Prefer real work evidence over started_at (auto-stamped on creation /
    # dependency clearance, so it usually predates any actual work).
    actual_start = effective_start or local_date(task.started_at)
    actual_end = local_date(task.completed_at)
    target_end = task.target_completion_date

    end_variance = None
    overdue = None
    start_variance = None

    if target_end is not None:
        if task.status == 'completed':
            end_variance = working_day_delta(target_end, actual_end, calendar)
        elif task.status not in ('cancelled', 'skipped') and today > target_end:
            past = working_day_delta(target_end, today, calendar)
            if past is not None and past > 0:
                overdue = past
    if task.target_start_date is not None:
        start_variance = working_day_delta(task.target_start_date, actual_start, calendar)

    return {
        'id': task.id,
        'job_no': task.job_order_id,
        'parent': task.parent_id,
        'department': task.department,
        'department_display': task.get_department_display(),
        'title': task.title,
        'task_type': task.task_type,
        'status': task.status,
        'status_display': task.get_status_display(),
        'sequence': task.sequence,
        'weight': task.weight,
        'assigned_to': task.assigned_to_id,
        'assigned_to_name': task.assigned_to.get_full_name() if task.assigned_to else None,
        'completion_percentage': float(completion_percentage),
        'depends_on': [dep.id for dep in task.depends_on.all()],
        'target_start_date': task.target_start_date,
        'target_completion_date': target_end,
        'started_at': task.started_at,
        'completed_at': task.completed_at,
        'schedule': {
            'actual_start_date': actual_start,
            'actual_end_date': actual_end,
            'start_variance_wd': float(start_variance) if start_variance is not None else None,
            'end_variance_wd': float(end_variance) if end_variance is not None else None,
            'overdue_wd': float(overdue) if overdue is not None else None,
            'classification': _classify(task.status, target_end, end_variance, overdue),
            # CNC tasks only: {'cuts_waiting', 'plate_items_pending'} when the job
            # has undelivered plate material — the delay belongs to procurement.
            'material_wait': material_wait,
            # Filled by _compute_forecast for open tasks:
            'projected_start_date': None,
            'projected_end_date': None,
            'projected_variance_wd': None,
            'pushed_by': None,
        },
    }


def _planned_duration(td, calendar):
    """Planned working-day length of the task's target window (>= default)."""
    duration = working_days_inclusive(
        td['target_start_date'], td['target_completion_date'], calendar
    )
    if duration is not None and duration > 0:
        return duration
    return DEFAULT_DURATION_WD


def _forecast_order(task_dicts, preds):
    """Kahn's topological order over the predecessor graph; any cycle
    leftovers are appended in stable (job, sequence, id) order and simply
    ignore their not-yet-projected predecessors."""
    indegree = {td['id']: 0 for td in task_dicts}
    successors = defaultdict(list)
    for tid, plist in preds.items():
        for pid in plist:
            successors[pid].append(tid)
            indegree[tid] += 1

    queue = [tid for tid, deg in indegree.items() if deg == 0]
    order = []
    while queue:
        tid = queue.pop()
        order.append(tid)
        for succ in successors[tid]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)

    if len(order) < len(indegree):
        by_id = {td['id']: td for td in task_dicts}
        seen = set(order)
        leftover = [tid for tid in indegree if tid not in seen]
        leftover.sort(key=lambda tid: (by_id[tid]['job_no'], by_id[tid]['sequence'], tid))
        order.extend(leftover)
    return order


def _compute_forecast(task_dicts, today, calendar):
    """Progress-aware schedule forecast + push propagation (mutates the
    ``schedule`` sub-dicts in place; never touches the database).

    Predecessors: explicit ``depends_on`` edges within the plan; main tasks
    without any fall back to the previous main task (by sequence) of the same
    job order — the department pipeline order.
    """
    by_id = {td['id']: td for td in task_dicts}

    mains_by_job = defaultdict(list)
    for td in task_dicts:
        if td['parent'] is None:
            mains_by_job[td['job_no']].append(td)

    implicit_pred = {}
    for mains in mains_by_job.values():
        ordered = sorted(mains, key=lambda t: (t['sequence'], t['id']))
        for prev, cur in zip(ordered, ordered[1:]):
            implicit_pred[cur['id']] = prev['id']

    preds = {}
    for td in task_dicts:
        explicit = [pid for pid in td['depends_on'] if pid in by_id]
        if not explicit and td['id'] in implicit_pred:
            explicit = [implicit_pred[td['id']]]
        preds[td['id']] = explicit

    projected_end = {}
    for tid in _forecast_order(task_dicts, preds):
        td = by_id[tid]
        sched = td['schedule']
        status = td['status']
        classification = sched['classification']

        if classification == 'excluded':
            projected_end[tid] = None
            continue
        if status == 'completed':
            # Fixed point for successors; nothing to forecast.
            projected_end[tid] = sched['actual_end_date']
            continue

        pushed_by = None
        started = status in ('in_progress', 'on_hold') and sched['actual_start_date'] is not None

        if started:
            # Project from the observed work rate.
            proj_start = sched['actual_start_date']
            progress = Decimal(str(td['completion_percentage'] or 0))
            elapsed = working_day_delta(proj_start, today, calendar) or ZERO
            if progress >= 100:
                end = today
            elif progress > 0 and elapsed > 0:
                remaining = min(
                    elapsed * (Decimal('100') - progress) / progress,
                    MAX_REMAINING_WD,
                )
                end = add_working_days(today, remaining, calendar)
            else:
                # No usable rate yet: assume the planned duration from today.
                end = span_end(today, _planned_duration(td, calendar), calendar)
        else:
            # Not started: re-anchor to today / target start / predecessors.
            base = max(today, td['target_start_date'] or today)
            dep_best_end, dep_src = None, None
            for pid in preds[tid]:
                pend = projected_end.get(pid)
                if pend is not None and (dep_best_end is None or pend > dep_best_end):
                    dep_best_end, dep_src = pend, pid
            proj_start = base
            if dep_best_end is not None:
                dep_clear = next_working_day(dep_best_end, calendar)
                if dep_clear > base:
                    proj_start = dep_clear
                    pushed_by = dep_src
            end = span_end(proj_start, _planned_duration(td, calendar), calendar)

        projected_end[tid] = end
        sched['projected_start_date'] = proj_start
        sched['projected_end_date'] = end
        sched['pushed_by'] = pushed_by

        target_end = td['target_completion_date']
        if target_end is not None and end is not None:
            variance = working_day_delta(target_end, end, calendar)
            sched['projected_variance_wd'] = float(variance) if variance is not None else None
            if (
                variance is not None and variance > 0
                and classification in ('in_progress', 'not_started')
            ):
                sched['classification'] = 'at_risk'


def _min_date(current, candidate):
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _max_date(current, candidate):
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def _summarize(task_dicts):
    summary = {key: 0 for key in CLASSIFICATION_KEYS}
    summary['total'] = len(task_dicts)
    summary['max_end_variance_wd'] = None
    summary['max_overdue_wd'] = None
    summary['max_projected_variance_wd'] = None
    planned_start = planned_end = actual_start = actual_end = projected_end = None

    for td in task_dicts:
        sched = td['schedule']
        summary[sched['classification']] += 1
        if sched['end_variance_wd'] is not None and sched['end_variance_wd'] > 0:
            summary['max_end_variance_wd'] = max(
                summary['max_end_variance_wd'] or 0, sched['end_variance_wd'])
        if sched['overdue_wd'] is not None:
            summary['max_overdue_wd'] = max(
                summary['max_overdue_wd'] or 0, sched['overdue_wd'])
        if sched['projected_variance_wd'] is not None and sched['projected_variance_wd'] > 0:
            summary['max_projected_variance_wd'] = max(
                summary['max_projected_variance_wd'] or 0, sched['projected_variance_wd'])
        if sched['classification'] != 'excluded':
            planned_start = _min_date(planned_start, td['target_start_date'])
            planned_end = _max_date(planned_end, td['target_completion_date'])
            actual_start = _min_date(actual_start, sched['actual_start_date'])
            actual_end = _max_date(actual_end, sched['actual_end_date'])
            projected_end = _max_date(projected_end, sched['projected_end_date'])

    summary['planned_window'] = {'start': planned_start, 'end': planned_end}
    summary['actual_window'] = {'start': actual_start, 'end': actual_end}
    # When the whole set finishes, everything is actual and this equals the
    # last actual end; while work is open it is the latest projected end.
    summary['projected_completion'] = _max_date(projected_end, actual_end)
    return summary


def _job_order_forecast(status, completed_at_date, target, task_dicts, calendar):
    """Will this job order finish on time?

    The job finishes when its last task finishes, so the projected completion
    is the latest per-task end (projected for open tasks, actual for
    completed ones) across the whole subtree. Verdicts:

    * ``finished_on_time`` / ``finished_late`` — the job is already completed.
    * ``on_track`` / ``late_risk`` — open job with a target date.
    * ``no_target`` — open job without a target date (projection still given).
    * ``unknown`` — nothing to project (no tasks).
    """
    forecast = {
        'target_completion_date': target,
        'projected_completion_date': None,
        'variance_wd': None,
        'verdict': 'unknown',
        'unplanned_open_tasks': sum(
            1 for td in task_dicts
            if td['schedule']['classification'] == 'unplanned'
            and td['status'] in OPEN_STATUSES
        ),
    }

    if status == 'completed':
        forecast['projected_completion_date'] = completed_at_date
        variance = working_day_delta(target, completed_at_date, calendar)
        forecast['variance_wd'] = float(variance) if variance is not None else None
        forecast['verdict'] = (
            'finished_late' if variance is not None and variance > 0 else 'finished_on_time'
        )
        return forecast

    ends = []
    for td in task_dicts:
        sched = td['schedule']
        if sched['classification'] == 'excluded':
            continue
        end = sched['projected_end_date'] or sched['actual_end_date']
        if end is not None:
            ends.append(end)
    if not ends:
        return forecast

    projected = max(ends)
    forecast['projected_completion_date'] = projected
    if target is None:
        forecast['verdict'] = 'no_target'
        return forecast

    variance = working_day_delta(target, projected, calendar)
    forecast['variance_wd'] = float(variance) if variance is not None else None
    forecast['verdict'] = 'late_risk' if variance is not None and variance > 0 else 'on_track'
    return forecast


def _natural_job_key(job_no):
    """Natural sort: 097-42 < 295-01 < 295-02, RM262-01 after numerics."""
    return [int(part) if part.isdigit() else part
            for part in re.split(r'(\d+)', job_no or '')]


def _visible_task_dicts(task_dicts):
    """Same rule as the frontend: a parent represented by its children is
    hidden, so card summaries match the detail table."""
    parent_ids = {td['parent'] for td in task_dicts if td['parent'] is not None}
    return [td for td in task_dicts if td['id'] not in parent_ids]


def build_production_plan_overview(status_filter='active'):
    """Portfolio payload: one verdict per ROOT job order, all computed in a
    fixed number of queries (~18) regardless of portfolio size.

    ``status_filter``: a JobOrder status, or 'all'.
    """
    roots_qs = (JobOrder.objects.filter(parent__isnull=True)
                .exclude(job_no='LEGACY-ARCHIVE')
                .select_related('customer'))
    if status_filter and status_filter != 'all':
        roots_qs = roots_qs.filter(status=status_filter)
    roots = sorted(roots_qs, key=lambda r: _natural_job_key(r.job_no))

    # Whole-table parent map (one query) -> subtree job list per root.
    children_map = defaultdict(list)
    for job_no, parent_id in JobOrder.objects.values_list('job_no', 'parent_id'):
        if parent_id:
            children_map[parent_id].append(job_no)

    subtree_jobs = {}
    all_job_nos = []
    for root in roots:
        stack, subtree = [root.job_no], []
        while stack:
            current = stack.pop()
            subtree.append(current)
            stack.extend(children_map.get(current, []))
        subtree_jobs[root.job_no] = subtree
        all_job_nos.extend(subtree)

    tasks = _fetch_tasks(all_job_nos)
    today = today_local()
    calendar = _build_calendar(tasks, today)
    progress_map = _compute_progress_map(tasks)
    effective_starts = _effective_start_map(tasks, _first_progress_evidence(all_job_nos))

    task_dicts_by_job = defaultdict(list)
    for task in tasks:
        td = _task_dict(task, calendar, today, progress_map[task.id],
                        effective_starts.get(task.id))
        task_dicts_by_job[task.job_order_id].append(td)

    items = []
    for root in roots:
        root_dicts = []
        for job_no in subtree_jobs[root.job_no]:
            root_dicts.extend(task_dicts_by_job.get(job_no, []))
        # Per root — matches the single-job endpoint by construction (a global
        # pass would honor cross-root depends_on edges the detail view drops).
        _compute_forecast(root_dicts, today, calendar)
        # Card meta counts follow the visible rule (parents represented by
        # children are hidden), but the windows/projected completion come from
        # ALL tasks, same as the detail hero timeline.
        summary = _summarize(_visible_task_dicts(root_dicts))
        full_summary = _summarize(root_dicts)
        summary['planned_window'] = full_summary['planned_window']
        summary['actual_window'] = full_summary['actual_window']
        summary['projected_completion'] = full_summary['projected_completion']
        summary['node_count'] = len(subtree_jobs[root.job_no])
        items.append({
            'job_no': root.job_no,
            'title': root.title,
            'customer_name': root.customer.name if root.customer_id else None,
            'status': root.status,
            'status_display': root.get_status_display(),
            'completion_percentage': float(root.completion_percentage),
            'forecast': _job_order_forecast(
                root.status, local_date(root.completed_at),
                root.target_completion_date, root_dicts, calendar,
            ),
            'summary': summary,
        })

    return {
        'items': items,
        'today': today,
        'generated_at': timezone.now(),
    }


def build_production_plan(root):
    """Assemble the full production-plan payload for a job order subtree."""
    nodes = _collect_subtree_nodes(root)
    job_nos = [node['job_no'] for node in nodes]
    tasks = _fetch_tasks(job_nos)
    today = today_local()
    calendar = _build_calendar(tasks, today)
    progress_map = _compute_progress_map(tasks)
    effective_starts = _effective_start_map(tasks, _first_progress_evidence(job_nos))

    tasks_by_job = defaultdict(list)
    for task in tasks:
        tasks_by_job[task.job_order_id].append(task)

    material_map = _material_wait_map(job_nos)

    # Build every task dict first (forecast pushes across job orders), keeping
    # the per-node association for the node summaries.
    all_task_dicts = []
    node_task_dicts = {}
    for node in nodes:
        dicts = [
            _task_dict(task, calendar, today, progress_map[task.id],
                       effective_starts.get(task.id),
                       material_wait=(material_map.get(task.job_order_id)
                                      if _task_domain(task) == 'cnc' else None))
            for task in _ordered_tasks(tasks_by_job.get(node['job_no'], []))
        ]
        node_task_dicts[node['job_no']] = dicts
        all_task_dicts.extend(dicts)

    _compute_forecast(all_task_dicts, today, calendar)

    for node in nodes:
        node['summary'] = _summarize(node_task_dicts[node['job_no']])

    overall = _summarize(all_task_dicts)
    overall['node_count'] = len(nodes)
    overall['main_tasks'] = sum(1 for td in all_task_dicts if td['parent'] is None)

    return {
        'job_order': {
            'job_no': root.job_no,
            'title': root.title,
            'customer_name': root.customer.name if root.customer_id else None,
            'status': root.status,
            'status_display': root.get_status_display(),
            'completion_percentage': float(root.completion_percentage),
            'target_completion_date': root.target_completion_date,
            'started_at': root.started_at,
            'completed_at': root.completed_at,
            'forecast': _job_order_forecast(
                root.status, local_date(root.completed_at),
                root.target_completion_date, all_task_dicts, calendar,
            ),
        },
        'nodes': nodes,
        'tasks': all_task_dicts,
        'summary': overall,
        'generated_at': timezone.now(),
        'today': today,
    }
