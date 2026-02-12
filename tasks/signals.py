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
    enqueue the parent Part for cost recalculation AND update job order progress.

    This mirrors machining.signals.enqueue_on_timer_change but for Parts/Operations.
    """
    operation_ct = ContentType.objects.get_for_model(Operation)
    if instance.content_type == operation_ct and instance.object_id:
        try:
            operation = Operation.objects.select_related('part').get(key=instance.object_id)

            # Existing: enqueue cost recalc
            PartCostRecalcQueue.objects.update_or_create(
                part=operation.part,
                defaults={'enqueued_at': timezone.now()}
            )

            # NEW: Update job order progress
            _update_job_order_for_operation(operation)

        except Operation.DoesNotExist:
            pass


def _update_job_order_for_operation(operation):
    """Update job orders that have a 'Talaşlı İmalat' task for this operation's part job_no."""
    from projects.models import JobOrder

    if not operation.part or not operation.part.job_no:
        return

    try:
        job_order = JobOrder.objects.get(job_no=operation.part.job_no)
        job_order.update_completion_percentage()

        # Check if Talaşlı İmalat subtask should auto-complete
        machining_subtask = job_order.department_tasks.filter(title='Talaşlı İmalat').first()
        if machining_subtask:
            machining_subtask.check_machining_auto_complete()

    except JobOrder.DoesNotExist:
        pass


@receiver(post_save, sender=Operation)
def update_job_order_on_operation_change(sender, instance, **kwargs):
    """
    When an Operation is saved (especially completion_date changes),
    update related JobOrder completion percentage.
    """
    if instance.part:
        _update_job_order_for_operation(instance)


@receiver(post_save, sender=Part)
def update_cached_job_no_on_part_update(sender, instance: Part, **kwargs):
    """
    When a Part's job_no changes, update the cached job_no in cost aggregates.
    This mirrors machining.signals.update_cached_job_no_on_task_rename.
    """
    from tasks.models import PartCostAgg, PartCostAggUser
    PartCostAgg.objects.filter(part=instance).update(job_no_cached=instance.job_no or "")
    PartCostAggUser.objects.filter(part=instance).update(job_no_cached=instance.job_no or "")


@receiver(post_save, sender=Part)
def update_job_order_on_part_change(sender, instance, **kwargs):
    """
    When a Part is saved (especially completion_date changes),
    update related JobOrder completion percentage.
    """
    _update_related_job_orders(instance)


def _update_related_job_orders(part):
    """Update job orders that have a 'Talaşlı İmalat' task for this part's job_no."""
    from projects.models import JobOrder

    if not part.job_no:
        return

    try:
        job_order = JobOrder.objects.get(job_no=part.job_no)
        job_order.update_completion_percentage()

        # Check if Talaşlı İmalat subtask should auto-complete
        machining_subtask = job_order.department_tasks.filter(title='Talaşlı İmalat').first()
        if machining_subtask:
            machining_subtask.check_machining_auto_complete()
    except JobOrder.DoesNotExist:
        pass