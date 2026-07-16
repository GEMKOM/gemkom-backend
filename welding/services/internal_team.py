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
    - parent_task must be welding (task_type == 'welding' or title == 'Kaynaklı İmalat')

    Note: welding tasks are themselves subtasks of a manufacturing main task, so we do
    NOT require parent_task.parent_id to be null — the is_welding check is the real guard
    (it prevents attaching to a non-welding sub-subtask).
    """
    # Identify welding parents by task_type OR legacy title (mirrors the CNC dual check).
    is_welding = parent_task.task_type == 'welding' or parent_task.title == 'Kaynaklı İmalat'
    if not is_welding:
        raise ValueError("Yalnızca 'Kaynaklı İmalat' görevi altına atama yapılabilir.")

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
