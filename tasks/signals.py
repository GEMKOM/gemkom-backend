from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from tasks.models import TaskFile, Timer, Operation, Part, PartCostRecalcQueue


@receiver(post_delete, sender=TaskFile)
def delete_file_on_taskfile_delete(sender, instance, **kwargs):
    """
    Deletes the actual file from storage when a TaskFile object is deleted.
    """
    if instance.file:
        instance.file.delete(save=False)


@receiver([post_save, post_delete], sender=Timer)
def enqueue_part_cost_recalc_on_timer_change(sender, instance: Timer, **kwargs):
    """
    When a Timer on an Operation is created/updated/deleted,
    enqueue the parent Part for cost recalculation.

    This mirrors machining.signals.enqueue_on_timer_change but for Parts/Operations.
    """
    operation_ct = ContentType.objects.get_for_model(Operation)
    if instance.content_type == operation_ct and instance.object_id:
        try:
            operation = Operation.objects.select_related('part').get(key=instance.object_id)
            PartCostRecalcQueue.objects.update_or_create(
                part=operation.part,
                defaults={'enqueued_at': timezone.now()}
            )
        except Operation.DoesNotExist:
            pass


@receiver(post_save, sender=Part)
def update_cached_job_no_on_part_update(sender, instance: Part, **kwargs):
    """
    When a Part's job_no changes, update the cached job_no in cost aggregates.
    This mirrors machining.signals.update_cached_job_no_on_task_rename.
    """
    from tasks.models import PartCostAgg, PartCostAggUser
    PartCostAgg.objects.filter(part=instance).update(job_no_cached=instance.job_no or "")
    PartCostAggUser.objects.filter(part=instance).update(job_no_cached=instance.job_no or "")