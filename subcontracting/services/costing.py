from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from subcontracting.models import SubcontractingAssignment, SubcontractorCostRecalcQueue


@transaction.atomic
def recompute_subcontractor_cost(job_no: str) -> Decimal:
    """
    Recalculate current_cost on every SubcontractingAssignment for this job order,
    then roll the total up to JobOrder.subcontractor_cost.

    Returns the new total subcontractor cost.
    """
    from projects.models import JobOrder

    assignments = list(
        SubcontractingAssignment.objects
        .filter(department_task__job_order_id=job_no)
        .select_related('price_tier', 'department_task')
    )

    total = Decimal('0.00')
    for assignment in assignments:
        assignment.recalculate_cost()
        assignment.save(update_fields=['current_cost', 'cost_currency'])
        total += assignment.current_cost

    try:
        job = JobOrder.objects.get(job_no=job_no)
        job.subcontractor_cost = total.quantize(Decimal('0.01'))
        job.save(update_fields=['subcontractor_cost'])
    except JobOrder.DoesNotExist:
        pass

    return total


def enqueue_subcontractor_cost_recalc(job_no: str) -> None:
    """Upsert the job_no into the recalc queue (idempotent)."""
    SubcontractorCostRecalcQueue.objects.update_or_create(
        job_no=job_no,
        defaults={}
    )
