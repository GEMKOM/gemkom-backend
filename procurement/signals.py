from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PurchaseRequest, PurchaseOrder


@receiver(post_save, sender=PurchaseRequest)
def update_job_order_on_pr_change(sender, instance, **kwargs):
    """Update job order progress when PR status changes."""
    _update_related_job_orders(instance)


@receiver(post_save, sender=PurchaseOrder)
def update_job_order_on_po_change(sender, instance, **kwargs):
    """Update job order progress when PO status changes (especially paid)."""
    if instance.pr:
        _update_related_job_orders(instance.pr)


def _update_related_job_orders(purchase_request):
    """Update all job orders related to this purchase request."""
    from projects.models import JobOrder

    # Collect job numbers from PurchaseRequestItems with direct FK
    job_nos = set()
    for pri_item in purchase_request.request_items.all():
        if pri_item.planning_request_item and pri_item.planning_request_item.job_no:
            job_nos.add(pri_item.planning_request_item.job_no)

    # Update each job order
    for job_no in job_nos:
        try:
            job_order = JobOrder.objects.get(job_no=job_no)
            job_order.update_completion_percentage()

            # Check if procurement task should auto-complete
            procurement_task = job_order.department_tasks.filter(
                department='procurement',
                parent__isnull=True
            ).first()
            if procurement_task:
                procurement_task.check_auto_complete()

        except JobOrder.DoesNotExist:
            pass
