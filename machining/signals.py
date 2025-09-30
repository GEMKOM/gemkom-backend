# machining/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from machining.models import JobCostRecalcQueue
from machining.models import Timer  # adjust path if different app
from users.models import WageRate

def _enqueue(job_no: str):
    if not job_no:
        return
    # upsert-like behavior
    JobCostRecalcQueue.objects.update_or_create(
        job_no=job_no, defaults={}
    )

@receiver([post_save, post_delete], sender=Timer)
def enqueue_on_timer_change(sender, instance: Timer, **kwargs):
    job_no = getattr(getattr(instance, "issue_key", None), "job_no", None)
    if job_no:
        _enqueue(job_no)

@receiver([post_save, post_delete], sender=WageRate)
def enqueue_on_wage_change(sender, instance: WageRate, **kwargs):
    from machining.models import Timer
    qs = (
        Timer.objects
        .filter(user_id=instance.user_id)
        .select_related("issue_key")
        .values_list("issue_key__job_no", flat=True)
        .distinct()
    )
    for j in qs:
        if j:
            _enqueue(j)
