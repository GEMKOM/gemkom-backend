from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.db import transaction
from rest_framework import serializers as drf_serializers

from projects.models import JobOrderDepartmentTask
from subcontracting.models import Subcontractor
from subcontracting.serializers import SubcontractingAssignmentSerializer


def create_subcontracting_assignment_with_subtask(
    *,
    kaynak_task: JobOrderDepartmentTask,
    subcontractor_id,
    price_tier_id,
    allocated_weight_kg,
    title: str = '',
    created_by=None,
    context=None,
):
    """
    Atomically create a 'subcontracting' subtask under a welding parent task and link
    it to a subcontractor + existing price tier.

    Single-sourced money-path logic reused by:
      - SubcontractingAssignmentViewSet.create_with_subtask (welding branch)
      - welding WeldingPlanAllocationViewSet.promote (subcontractor promotion)

    Validation of the parent (welding + main task) and the tier's remaining capacity is
    performed by SubcontractingAssignmentSerializer.validate(), which also takes a
    select_for_update lock on the tier — so `context` must carry the request.

    Returns the created SubcontractingAssignment. Raises drf ValidationError on bad input.
    """
    title = (title or '').strip()
    if not title:
        try:
            title = Subcontractor.objects.get(pk=subcontractor_id).name
        except Subcontractor.DoesNotExist:
            raise drf_serializers.ValidationError({'subcontractor': 'Taşeron bulunamadı.'})

    subtask_weight = max(1, round(Decimal(str(allocated_weight_kg))))
    next_sequence = (
        kaynak_task.subtasks.aggregate(m=models.Max('sequence'))['m'] or 0
    ) + 1

    with transaction.atomic():
        subtask = JobOrderDepartmentTask.objects.create(
            job_order=kaynak_task.job_order,
            department=kaynak_task.department,
            parent=kaynak_task,
            title=title,
            task_type='subcontracting',
            status='in_progress',
            weight=subtask_weight,
            sequence=next_sequence,
            created_by=created_by,
        )

        serializer = SubcontractingAssignmentSerializer(
            data={
                'department_task': subtask.pk,
                'subcontractor': subcontractor_id,
                'price_tier': price_tier_id,
                'allocated_weight_kg': allocated_weight_kg,
            },
            context=context or {},
        )
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save(created_by=created_by)

    return assignment
