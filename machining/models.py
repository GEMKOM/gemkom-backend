from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth.models import User

from machines.models import Machine
from django.db.models import Q

class TaskKeyCounter(models.Model):
    prefix = models.CharField(max_length=10, default='TI', unique=True)
    current = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.prefix}-{self.current}"


class Task(models.Model):
    key = models.CharField(max_length=255, primary_key=True)  # Matches Timer.issue_key
    name = models.CharField(max_length=255)
    job_no = models.CharField(max_length=255, null=True, blank=True)
    image_no = models.CharField(max_length=255, null=True, blank=True)
    position_no = models.CharField(max_length=255, null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    completion_date = models.BigIntegerField(null=True, blank=True)
    is_hold_task = models.BooleanField(default=False)
    estimated_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    machine_fk = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='machine_tasks')
    finish_time = models.DateField(null=True, blank=True)

    # Planning (set by frontend save)
    in_plan = models.BooleanField(default=False, db_index=True)
    planned_start_ms = models.BigIntegerField(null=True, blank=True)
    planned_end_ms = models.BigIntegerField(null=True, blank=True)
    plan_order = models.IntegerField(null=True, blank=True)
    plan_locked = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
    class Meta:
        constraints = [
            # Only enforce unique order for items that are actually in the plan
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
    

class Timer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_timers')
    stopped_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='stopped_timers')
    issue_key = models.ForeignKey(Task, on_delete=models.CASCADE, to_field='key', db_column='issue_key', related_name='timers')
    start_time = models.BigIntegerField()
    finish_time = models.BigIntegerField(null=True, blank=True)
    manual_entry = models.BooleanField(default=False)
    comment = models.TextField(null=True, blank=True)
    machine = models.CharField(max_length=255, null=True, blank=True)
    machine_fk = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='machine_timers')
    

    class Meta:
        ordering = ['-start_time']


# machining/models.py (add at bottom)
from django.db import models

class JobCostAgg(models.Model):
    job_no = models.CharField(max_length=100, primary_key=True)
    currency = models.CharField(max_length=3, default="EUR")
    hours_ww = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_ah = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_su = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cost_ww  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_ah  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_su  = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.job_no} total={self.total_cost} {self.currency}"

class JobCostAggUser(models.Model):
    job_no = models.CharField(max_length=100)
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE)
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
        unique_together = ("job_no", "user")

    def __str__(self):
        return f"{self.job_no} / {self.user} = {self.total_cost} {self.currency}"

class JobCostRecalcQueue(models.Model):
    job_no = models.CharField(max_length=100, primary_key=True)
    enqueued_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.job_no} @ {self.enqueued_at}"
