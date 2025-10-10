from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from machines.models import Machine


class TaskKeyCounter(models.Model):
    """
    Generic counter for any task type. The prefix (e.g., 'TI', 'CNC')
    differentiates the counters.
    """
    prefix = models.CharField(max_length=10, unique=True)
    current = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.prefix}-{self.current}"


class BaseTask(models.Model):
    """
    Abstract base model for all types of tasks (Machining, CNC, etc.).
    Contains all the common fields.
    """
    key = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255)
    quantity = models.IntegerField(null=True, blank=True)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    completion_date = models.BigIntegerField(null=True, blank=True)
    is_hold_task = models.BooleanField(default=False)
    estimated_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    machine_fk = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='%(app_label)s_%(class)s_related')
    finish_time = models.DateField(null=True, blank=True)

    # Planning fields are common
    in_plan = models.BooleanField(default=False, db_index=True)
    planned_start_ms = models.BigIntegerField(null=True, blank=True)
    planned_end_ms = models.BigIntegerField(null=True, blank=True)
    plan_order = models.IntegerField(null=True, blank=True)
    plan_locked = models.BooleanField(default=False)

    class Meta:
        abstract = True # This is crucial! It means this model won't create a DB table.

    def __str__(self):
        return self.name


class Timer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='new_started_timers')
    stopped_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='new_stopped_timers')
    start_time = models.BigIntegerField()
    finish_time = models.BigIntegerField(null=True, blank=True)
    manual_entry = models.BooleanField(default=False)
    comment = models.TextField(null=True, blank=True)
    machine_fk = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name='new_machine_timers')

    # Generic Foreign Key to link to any Task type
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255) # Use CharField to match Task's primary key
    issue_key = GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-start_time']
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

