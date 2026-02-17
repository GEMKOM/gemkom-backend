from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal


@receiver(post_save, sender='planning.PlanningRequestItem')
def reopen_procurement_task_on_new_item(sender, instance, created, **kwargs):
    """
    When a new PlanningRequestItem is created with quantity_to_purchase > 0,
    check if the procurement task for that job was already completed.
    If so, uncomplete it so the new item is tracked.
    """
    if not created:
        return

    if not instance.job_no or instance.quantity_to_purchase <= Decimal('0'):
        return

    from projects.models import JobOrderDepartmentTask

    completed_tasks = JobOrderDepartmentTask.objects.filter(
        job_order__job_no=instance.job_no,
        department='procurement',
        status='completed',
    ).select_related('job_order')

    for task in completed_tasks:
        task.uncomplete()
