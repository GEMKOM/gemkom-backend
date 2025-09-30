# machining/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from machining.models import JobCostAgg, JobCostAggUser, JobCostRecalcQueue, Task
from machining.models import Timer  # adjust path if different app
from users.models import WageRate

def _enqueue_task(task_id: int):
    from machining.models import JobCostRecalcQueue
    JobCostRecalcQueue.objects.update_or_create(task_id=task_id, defaults={})

@receiver([post_save, post_delete], sender=Timer)
def enqueue_on_timer_change(sender, instance: Timer, **kwargs):
    if instance.issue_key_id:
        _enqueue_task(instance.issue_key_id)

@receiver([post_save, post_delete], sender=WageRate)
def enqueue_on_wage_change(sender, instance: WageRate, **kwargs):
    from machining.models import Timer
    task_ids = (Timer.objects.filter(user_id=instance.user_id)
                .values_list("issue_key_id", flat=True).distinct())
    for tid in task_ids:
        if tid:
            _enqueue_task(tid)

@receiver(post_save, sender=Task)
def update_cached_job_no_on_task_rename(sender, instance: Task, **kwargs):
    # keep snapshots' label in sync; cheap, no recompute needed
    JobCostAgg.objects.filter(task=instance).update(job_no_cached=instance.job_no or "")
    JobCostAggUser.objects.filter(task=instance).update(job_no_cached=instance.job_no or "")
