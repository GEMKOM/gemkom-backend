"""
Production phase support for job orders.

Planning can split an engineering job order (e.g. 270-01) into one or more
production phases (270-01/P1, 270-01/P2). Each phase is created as a *child*
JobOrder of the engineering job, with ``source_job_order`` pointing back to it.

Modelling phases as children of the engineering node means the existing
parent-child machinery — completion roll-up, status cascade, cost roll-up — keeps
working without any special-casing. The only new concept is the ``/P{n}`` mirror
job and the non-engineering department tasks copied into it.
"""
from collections import deque

from django.db import transaction

from projects.models import JobOrder, JobOrderDepartmentTask


# Engineering work stays on the source job; only downstream (production) work is
# mirrored into each phase.
ENGINEERING_DEPARTMENTS = {'design'}


def _iter_engineering_tree(source_root_job):
    """
    BFS-walk the engineering job tree rooted at *source_root_job*, yielding every
    job order in it. Phase mirror jobs (and their subtrees) are skipped so that
    re-running phase creation never copies tasks out of previously created phases.
    """
    queue = deque([source_root_job])
    while queue:
        job = queue.popleft()
        yield job
        for child in job.children.all():
            # Don't descend into phase mirrors — they are production, not engineering.
            if child.source_job_order_id is not None:
                continue
            queue.append(child)


def _collect_production_main_tasks(source_root_job):
    """
    Return the non-engineering main department tasks (parent is null) found by
    BFS-walking the engineering tree, each with its subtasks prefetched.
    """
    main_tasks = []
    for job in _iter_engineering_tree(source_root_job):
        tasks = (
            job.department_tasks
            .filter(parent__isnull=True)
            .exclude(department__in=ENGINEERING_DEPARTMENTS)
            .prefetch_related('subtasks')
            .order_by('sequence')
        )
        main_tasks.extend(tasks)
    return main_tasks


def _copy_task(source_task, target_job, parent=None):
    """Create a pending copy of *source_task* on *target_job*."""
    return JobOrderDepartmentTask.objects.create(
        job_order=target_job,
        parent=parent,
        department=source_task.department,
        title=source_task.title,
        task_type=source_task.task_type,
        description=source_task.description,
        status='pending',
        weight=source_task.weight,
        manual_progress=0,
        target_start_date=source_task.target_start_date,
        target_completion_date=source_task.target_completion_date,
        sequence=source_task.sequence,
    )


@transaction.atomic
def create_phases(source_root_job, phases, user=None):
    """
    Split an engineering job order into production phases.

    For each entry in *phases* a mirror :class:`JobOrder` named
    ``"{source_root_job.job_no}/P{n}"`` is created as a child of
    *source_root_job* (with ``source_job_order`` pointing back to it). Each phase
    receives a pending copy of every non-engineering department task found by
    BFS-walking the engineering tree, so the phase can be activated independently
    later via :func:`activate_phase`.

    Args:
        source_root_job: the engineering :class:`JobOrder` to split.
        phases: list of dicts describing each phase. Recognised keys:
            ``phase_number`` (defaults to 1-based position),
            ``title`` (defaults to "{source title} - Faz {n}"),
            ``target_completion_date``, ``priority``.
        user: the user performing the split (recorded as created_by).

    Returns:
        list of the created phase :class:`JobOrder` instances.
    """
    if source_root_job.is_phase_job:
        raise ValueError("Bir faz iş emri yeniden fazlara bölünemez.")
    if not phases:
        raise ValueError("En az bir faz tanımlanmalıdır.")

    existing_numbers = set(
        source_root_job.phase_mirrors.values_list('phase_number', flat=True)
    )
    production_tasks = _collect_production_main_tasks(source_root_job)

    created = []
    for idx, spec in enumerate(phases, start=1):
        phase_number = spec.get('phase_number') or idx
        if phase_number in existing_numbers:
            raise ValueError(f"Faz {phase_number} bu iş emri için zaten mevcut.")
        existing_numbers.add(phase_number)

        phase_job_no = f"{source_root_job.job_no}/P{phase_number}"
        if JobOrder.objects.filter(job_no=phase_job_no).exists():
            raise ValueError(f"'{phase_job_no}' iş emri numarası zaten kullanımda.")

        phase = JobOrder.objects.create(
            job_no=phase_job_no,
            parent=source_root_job,
            source_job_order=source_root_job,
            phase_number=phase_number,
            title=spec.get('title') or f"{source_root_job.title} - Faz {phase_number}",
            quantity=source_root_job.quantity,
            customer=source_root_job.customer,
            customer_order_no=source_root_job.customer_order_no,
            priority=spec.get('priority') or source_root_job.priority,
            target_completion_date=spec.get('target_completion_date'),
            status='draft',
            created_by=user,
        )

        # Copy production tasks into the phase as pending. Two passes so that
        # depends_on can be remapped onto the phase's own task copies.
        source_to_copy = {}
        for source_task in production_tasks:
            copy = _copy_task(source_task, phase)
            source_to_copy[source_task.pk] = copy
            for subtask in source_task.subtasks.all():
                _copy_task(subtask, phase, parent=copy)

        # Remap main-task dependencies onto the phase copies.
        for source_task in production_tasks:
            dep_ids = list(source_task.depends_on.values_list('pk', flat=True))
            mapped = [source_to_copy[d] for d in dep_ids if d in source_to_copy]
            if mapped:
                source_to_copy[source_task.pk].depends_on.set(mapped)

        created.append(phase)

    return created


def activate_phase(phase_root_job, user=None):
    """
    Activate a production phase. Delegates to :meth:`JobOrder.start`, which moves
    the phase from draft to active and cascades to its tasks/children.
    """
    if not phase_root_job.is_phase_job:
        raise ValueError("Bu iş emri bir üretim fazı değil.")
    if phase_root_job.status != 'draft':
        raise ValueError("Sadece taslak durumundaki fazlar etkinleştirilebilir.")
    phase_root_job.start(user=user)
    return phase_root_job
