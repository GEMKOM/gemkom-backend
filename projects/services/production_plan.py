"""
Full-subtree production plan for a job order.

Builds the payload for ``GET /projects/job-orders/{job_no}/production-plan/``:
every department task (main tasks + subtasks) of the job order and all of its
descendant job orders — including phase nodes and allocations — with planned
vs. actual dates, working-day lateness and per-node / overall rollups.

Read-only. Query cost is ~(tree depth + 5) regardless of tree size: one
JobOrder query per depth level, one query for phased-master detection, one
for all tasks (+2 prefetches), one for the holiday calendar.
"""
from collections import defaultdict

from django.utils import timezone

from projects.models import JobOrder, JobOrderDepartmentTask
from projects.services.schedule import (
    load_holiday_calendar,
    local_date,
    today_local,
    working_day_delta,
)

_JOB_STATUS_DISPLAY = dict(JobOrder.STATUS_CHOICES)

_NODE_VALUES = (
    'job_no', 'parent_id', 'title', 'status', 'completion_percentage',
    'target_completion_date', 'quantity', 'phase_number', 'source_job_order_id',
)

CLASSIFICATION_KEYS = (
    'completed_on_time', 'completed_late', 'overdue',
    'in_progress', 'not_started', 'unplanned', 'excluded',
)


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
        .select_related('assigned_to')
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


def _build_calendar(tasks, today):
    """One holiday query spanning every date the lateness math can touch."""
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
    return load_holiday_calendar(min(dates), max(dates))


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


def _task_dict(task, calendar, today):
    actual_start = local_date(task.started_at)
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
        'completion_percentage': float(task.get_completion_percentage(skip_expensive_calculations=True)),
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
        },
    }


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
    planned_start = planned_end = actual_start = actual_end = None

    for td in task_dicts:
        sched = td['schedule']
        summary[sched['classification']] += 1
        if sched['end_variance_wd'] is not None and sched['end_variance_wd'] > 0:
            summary['max_end_variance_wd'] = max(
                summary['max_end_variance_wd'] or 0, sched['end_variance_wd'])
        if sched['overdue_wd'] is not None:
            summary['max_overdue_wd'] = max(
                summary['max_overdue_wd'] or 0, sched['overdue_wd'])
        if sched['classification'] != 'excluded':
            planned_start = _min_date(planned_start, td['target_start_date'])
            planned_end = _max_date(planned_end, td['target_completion_date'])
            actual_start = _min_date(actual_start, sched['actual_start_date'])
            actual_end = _max_date(actual_end, sched['actual_end_date'])

    summary['planned_window'] = {'start': planned_start, 'end': planned_end}
    summary['actual_window'] = {'start': actual_start, 'end': actual_end}
    return summary


def build_production_plan(root):
    """Assemble the full production-plan payload for a job order subtree."""
    nodes = _collect_subtree_nodes(root)
    job_nos = [node['job_no'] for node in nodes]
    tasks = _fetch_tasks(job_nos)
    today = today_local()
    calendar = _build_calendar(tasks, today)

    tasks_by_job = defaultdict(list)
    for task in tasks:
        tasks_by_job[task.job_order_id].append(task)

    all_task_dicts = []
    for node in nodes:
        node_dicts = [
            _task_dict(task, calendar, today)
            for task in _ordered_tasks(tasks_by_job.get(node['job_no'], []))
        ]
        node['summary'] = _summarize(node_dicts)
        all_task_dicts.extend(node_dicts)

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
        },
        'nodes': nodes,
        'tasks': all_task_dicts,
        'summary': overall,
        'generated_at': timezone.now(),
        'today': today,
    }
