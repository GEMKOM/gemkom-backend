from decimal import Decimal

from django.db import transaction
from django.db.models import Max

from projects.models import JobOrderDepartmentTask
from welding.models import InternalTeamAssignment


def create_internal_team_assignment(
    *,
    parent_task: JobOrderDepartmentTask,
    team,
    allocated_weight_kg: Decimal,
    title: str = '',
    notes: str = '',
    created_by=None,
) -> tuple[JobOrderDepartmentTask, InternalTeamAssignment]:
    """
    Atomically create an 'internal_team' subtask under parent_task and link it to a Team.

    Validation:
    - parent_task.task_type must be 'welding'
    - parent_task must be a main task (parent_id is None)
    """
    if parent_task.task_type != 'welding':
        raise ValueError("Yalnızca 'Kaynaklı İmalat' görevi altına atama yapılabilir.")
    if parent_task.parent_id is not None:
        raise ValueError("Dahili takım ataması yalnızca ana göreve yapılabilir, alt göreve değil.")

    next_seq = (
        parent_task.subtasks.aggregate(m=Max('sequence'))['m'] or 0
    ) + 1

    weight = max(1, round(Decimal(str(allocated_weight_kg))))

    with transaction.atomic():
        subtask = JobOrderDepartmentTask.objects.create(
            job_order=parent_task.job_order,
            department=parent_task.department,
            parent=parent_task,
            title=title or team.name,
            task_type='internal_team',
            status='in_progress',
            weight=weight,
            sequence=next_seq,
            created_by=created_by,
        )
        assignment = InternalTeamAssignment.objects.create(
            department_task=subtask,
            team=team,
            allocated_weight_kg=allocated_weight_kg,
            notes=notes,
            created_by=created_by,
        )

    return subtask, assignment
