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
    planned_start_ms = models.BigIntegerField(null=True, blank=True)
    planned_end_ms = models.BigIntegerField(null=True, blank=True)
    plan_order = models.IntegerField(null=True, blank=True)
    plan_locked = models.BooleanField(default=False)

    def __str__(self):
        return self.name
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['machine_fk', 'plan_order'],
                name='uniq_machine_plan_order',
                condition=models.Q(plan_order__isnull=False),
            ),
        ]
        indexes = [
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

