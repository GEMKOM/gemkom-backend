from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import CncTask


@receiver(post_save, sender=CncTask)
def update_job_order_on_cnc_task_change(sender, instance, **kwargs):
    """Update job order progress when CncTask completion status changes."""
    _update_related_job_orders(instance)


def _update_related_job_orders(cnc_task):
    """Update all job orders related to this CncTask via its parts."""
    from projects.models import JobOrder

    # Collect unique job numbers from CncParts
    job_nos = set(cnc_task.parts.values_list('job_no', flat=True))

    for job_no in job_nos:
        if not job_no:
            continue
        try:
            job_order = JobOrder.objects.get(job_no=job_no)
            job_order.update_completion_percentage()

            # Check if CNC Kesim subtask should auto-complete
            cnc_subtask = job_order.department_tasks.filter(
                title='CNC Kesim'
            ).first()
            if cnc_subtask:
                cnc_subtask.check_cnc_auto_complete()

        except JobOrder.DoesNotExist:
            pass
