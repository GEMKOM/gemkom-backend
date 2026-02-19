import threading

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from projects.models import JobOrderDepartmentTask

# Thread-local state: deduplicate job_nos within a single request transaction.
_pending = threading.local()


def _get_pending_jobs() -> set:
    if not hasattr(_pending, 'jobs'):
        _pending.jobs = set()
    return _pending.jobs


def _is_scheduled() -> bool:
    return getattr(_pending, 'scheduled', False)


def _set_scheduled(value: bool):
    _pending.scheduled = value


def _flush_cost_updates():
    """
    Runs once after the transaction commits.
    Recalculates subcontractor costs for all queued job orders.
    Falls back to enqueuing if recalculation fails.
    """
    from subcontracting.services.costing import (
        enqueue_subcontractor_cost_recalc,
        recompute_subcontractor_cost,
    )

    jobs = _get_pending_jobs().copy()
    _get_pending_jobs().clear()
    _set_scheduled(False)

    for job_no in jobs:
        try:
            recompute_subcontractor_cost(job_no)
        except Exception:
            # Best-effort: enqueue for background drain
            try:
                enqueue_subcontractor_cost_recalc(job_no)
            except Exception:
                pass


def _schedule_cost_update(job_no: str):
    _get_pending_jobs().add(job_no)
    if not _is_scheduled():
        _set_scheduled(True)
        transaction.on_commit(_flush_cost_updates)


@receiver(post_save, sender=JobOrderDepartmentTask)
def on_department_task_saved(sender, instance, **kwargs):
    """
    When a manufacturing subtask that has a subcontracting assignment is saved,
    schedule a cost recalculation for its job order.

    Uses transaction.on_commit + thread-local deduplication to avoid
    infinite loops and redundant recalculations.
    """
    # Only care about subtasks (have a parent)
    if not instance.parent_id:
        return
    if instance.department != 'manufacturing':
        return

    # Cheap check: does this task have a subcontracting assignment?
    # We access the reverse OneToOne via a try/except to avoid extra DB hits
    # on tasks that are not subcontracting tasks.
    try:
        _ = instance.subcontracting_assignment
    except Exception:
        return

    _schedule_cost_update(instance.job_order_id)
