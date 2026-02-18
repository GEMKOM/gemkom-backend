import threading

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PurchaseRequest, PurchaseOrder, PurchaseOrderLine, PaymentSchedule

# Thread-local state: collects PR pks to update, runs once on commit
_pending = threading.local()


def _get_pending_prs() -> set:
    if not hasattr(_pending, 'prs'):
        _pending.prs = set()
    return _pending.prs


def _get_scheduled() -> bool:
    return getattr(_pending, 'scheduled', False)


def _set_scheduled(value: bool):
    _pending.scheduled = value


def _flush_job_order_updates():
    """Called once after transaction commit. Processes all collected PR pks at once."""
    from projects.models import JobOrder

    prs = _get_pending_prs().copy()
    _get_pending_prs().clear()
    _set_scheduled(False)

    if not prs:
        return

    # Collect all unique job numbers across all pending PRs
    job_nos = set()
    for pr in PurchaseRequest.objects.filter(pk__in=prs).prefetch_related(
        'request_items__planning_request_item'
    ):
        for pri_item in pr.request_items.all():
            if pri_item.planning_request_item and pri_item.planning_request_item.job_no:
                job_nos.add(pri_item.planning_request_item.job_no)

    if not job_nos:
        return

    # Update each job order once
    for job_order in JobOrder.objects.filter(job_no__in=job_nos):
        job_order.update_completion_percentage()

        procurement_task = job_order.department_tasks.filter(
            department='procurement',
            parent__isnull=True
        ).first()
        if procurement_task:
            procurement_task.check_auto_complete()


def _schedule_job_order_update(pr_pk):
    """Add a PR pk to the pending set and schedule a single on_commit flush."""
    _get_pending_prs().add(pr_pk)
    if not _get_scheduled():
        _set_scheduled(True)
        transaction.on_commit(_flush_job_order_updates)


@receiver(post_save, sender=PurchaseRequest)
def update_job_order_on_pr_change(sender, instance, **kwargs):
    _schedule_job_order_update(instance.pk)


@receiver(post_save, sender=PurchaseOrder)
def update_job_order_on_po_change(sender, instance, **kwargs):
    if instance.pr_id:
        _schedule_job_order_update(instance.pr_id)


@receiver(post_save, sender=PaymentSchedule)
def update_job_order_on_payment(sender, instance, **kwargs):
    if instance.purchase_order_id:
        po = instance.purchase_order
        if po.pr_id:
            _schedule_job_order_update(po.pr_id)


@receiver(post_save, sender=PurchaseOrderLine)
def update_job_order_on_delivery(sender, instance, **kwargs):
    if instance.po_id:
        po = instance.po
        if po.pr_id:
            _schedule_job_order_update(po.pr_id)
