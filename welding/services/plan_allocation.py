from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

from welding.models import WeldingPlanAllocation


def build_overallocation_warnings(department_task_ids) -> list[dict]:
    """
    Return a soft warning for every main welding task whose total planned allocation
    exceeds the job order's total_weight_kg.

    This is advisory only — planners must be able to over-allocate while playing with
    scenarios, so callers surface these but never block on them.

    Each warning: {department_task_id, job_no, allocated_total, total_weight_kg}.
    Tasks whose job order has no total_weight_kg (nullable) are skipped.
    """
    ids = [int(i) for i in department_task_ids if i is not None]
    if not ids:
        return []

    rows = (
        WeldingPlanAllocation.objects
        .filter(department_task_id__in=ids)
        .values('department_task_id')
        .annotate(allocated_total=Sum('allocated_weight_kg'))
    )
    totals = {r['department_task_id']: (r['allocated_total'] or Decimal('0')) for r in rows}

    if not totals:
        return []

    from projects.models import JobOrderDepartmentTask
    tasks = (
        JobOrderDepartmentTask.objects
        .filter(pk__in=totals.keys())
        .select_related('job_order')
    )

    warnings = []
    for task in tasks:
        job_order = task.job_order
        total_weight_kg = getattr(job_order, 'total_weight_kg', None)
        if total_weight_kg is None:
            continue
        allocated_total = totals.get(task.pk, Decimal('0'))
        if allocated_total > total_weight_kg:
            warnings.append({
                'department_task_id': task.pk,
                'job_no': task.job_order_id,
                'allocated_total': allocated_total,
                'total_weight_kg': total_weight_kg,
            })
    return warnings
