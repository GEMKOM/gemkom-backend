# machining/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType

from machining.models import JobCostAgg, JobCostAggUser, JobCostRecalcQueue, Task
from tasks.models import Timer  # adjust path if different app
from users.models import WageRate

def _enqueue_task(task_id: int):
    # JobCostRecalcQueue is in the machining app
    JobCostRecalcQueue.objects.update_or_create(task_id=task_id, defaults={})

@receiver([post_save, post_delete], sender=Timer)
def enqueue_on_timer_change(sender, instance: Timer, **kwargs):
    """
    When a Timer is created/updated/deleted, enqueue its related Task for a cost recalculation,
    but only if the timer belongs to a machining.Task.
    """
    task_content_type = ContentType.objects.get_for_model(Task)
    if instance.content_type == task_content_type and instance.object_id:
        _enqueue_task(instance.object_id)

@receiver([post_save, post_delete], sender=WageRate)
def enqueue_on_wage_change(sender, instance: WageRate, **kwargs):
    """
    When a user's wage changes, re-enqueue all machining tasks they have worked on.
    """
    task_content_type = ContentType.objects.get_for_model(Task)
    
    # Find all distinct machining task IDs this user has timers for.
    task_ids = (
        Timer.objects.filter(
            user_id=instance.user_id,
            content_type=task_content_type
        )
        .values_list("object_id", flat=True)
        .distinct()
    )
    for tid in task_ids:
        if tid:
            _enqueue_task(tid)

@receiver(post_save, sender=Task)
def update_cached_job_no_on_task_rename(sender, instance: Task, **kwargs):
    # keep snapshots' label in sync; cheap, no recompute needed
    JobCostAgg.objects.filter(task=instance).update(job_no_cached=instance.job_no or "")
    JobCostAggUser.objects.filter(task=instance).update(job_no_cached=instance.job_no or "")
