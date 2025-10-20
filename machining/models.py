from django.db import models
from django.db.models import Q
from tasks.models import BaseTask

from django.contrib.contenttypes.fields import GenericRelation

class Task(BaseTask):
    """
    A machining-specific task. Inherits common fields from BaseTask
    and adds fields unique to machining.
    """
    job_no = models.CharField(max_length=255, null=True, blank=True)
    image_no = models.CharField(max_length=255, null=True, blank=True)
    position_no = models.CharField(max_length=255, null=True, blank=True)
    
    # This creates the reverse relationship from a Task back to all its Timers.
    # It allows `prefetch_related('issue_key')` to work on Task querysets.
    issue_key = GenericRelation(
        'tasks.Timer',
        content_type_field='content_type',
        object_id_field='object_id',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['machine_fk', 'plan_order'],
                name='uniq_machine_plan_order_active',
                condition=models.Q(plan_order__isnull=False, in_plan=True),
            ),
        ]
        indexes = [
            models.Index(fields=['machine_fk', 'in_plan']),
            models.Index(fields=['machine_fk', 'plan_order']),
            models.Index(fields=['machine_fk', 'planned_start_ms']),
        ]

    def save(self, *args, **kwargs):
        if self.completion_date is not None:
            # Completed tasks must not occupy plan slots
            self.in_plan = False
            self.plan_order = None
            # Optionally clear other planning fields:
            # self.planned_start_ms = None
            # self.planned_end_ms = None
            # self.plan_locked = False
        if self.pk:
            try:
                old = Task.objects.only('machine_fk').get(pk=self.pk)
                if old.machine_fk_id != (self.machine_fk_id or None):
                    self.in_plan = False
                    self.plan_order = None
                    self.planned_start_ms = None
                    self.planned_end_ms = None
            except Task.DoesNotExist:
                pass

        super().save(*args, **kwargs)    

# machining/models.py (add at bottom)
from django.db import models

class JobCostAgg(models.Model):
    task = models.OneToOneField("machining.Task", on_delete=models.CASCADE, primary_key=True)
    job_no_cached = models.CharField(max_length=100, db_index=True)  # display/filter
    currency = models.CharField(max_length=3, default="EUR")
    hours_ww = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_ah = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_su = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_ww  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_ah  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_su  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

class JobCostAggUser(models.Model):
    task = models.ForeignKey("machining.Task", on_delete=models.CASCADE)
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
    job_no_cached = models.CharField(max_length=100, db_index=True)
    currency = models.CharField(max_length=3, default="EUR")
    hours_ww = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_ah = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_su = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_ww  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_ah  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_su  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("task", "user")

class JobCostRecalcQueue(models.Model):
    task = models.OneToOneField("machining.Task", on_delete=models.CASCADE, primary_key=True)
    enqueued_at = models.DateTimeField(auto_now=True)
