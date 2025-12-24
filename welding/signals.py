# welding/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from welding.models import WeldingTimeEntry, WeldingJobCostRecalcQueue


@receiver(post_save, sender=WeldingTimeEntry)
def enqueue_welding_job_cost_on_save(sender, instance, **kwargs):
    """
    When a WeldingTimeEntry is created or updated, enqueue its job_no for cost recalculation.
    """
    if instance.job_no:
        WeldingJobCostRecalcQueue.objects.update_or_create(
            job_no=instance.job_no,
            defaults={}
        )


@receiver(post_delete, sender=WeldingTimeEntry)
def enqueue_welding_job_cost_on_delete(sender, instance, **kwargs):
    """
    When a WeldingTimeEntry is deleted, enqueue its job_no for cost recalculation.
    """
    if instance.job_no:
        WeldingJobCostRecalcQueue.objects.update_or_create(
            job_no=instance.job_no,
            defaults={}
        )
