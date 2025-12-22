from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
import os

from machines.models import Machine
from core.storages import PrivateMediaStorage

def task_attachment_upload_path(instance, filename):
    """Generic upload path for any task attachment."""
    # file will be uploaded to MEDIA_ROOT/task_attachments/<app_label>/<task_key>/<filename>
    return os.path.join('task_attachments', instance.content_type.app_label, str(instance.object_id), filename)

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
    description = models.TextField(null=True, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='%(app_label)s_%(class)s_created')
    created_at = models.BigIntegerField(null=True, blank=True)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='%(app_label)s_%(class)s_completed')
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
    
    # Generic relation to the new TaskFile model.
    # This allows `task.files.all()` to work on any BaseTask subclass.
    files = GenericRelation(
        'tasks.TaskFile',
        content_type_field='content_type',
        object_id_field='object_id')

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
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'machine_fk', 'content_type', 'object_id'],
                condition=models.Q(finish_time__isnull=True),
                name='unique_active_timer_per_user_machine_task'
            ),
        ]


class TaskFile(models.Model):
    """
    Represents a file attached to any task model that inherits from BaseTask.
    """
    file = models.FileField(upload_to=task_attachment_upload_path, storage=PrivateMediaStorage())
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    # Generic Foreign Key to link to any Task type
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255) # Use CharField to match Task's primary key
    task = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        return f"File for {self.object_id} - {os.path.basename(self.file.name)}"
