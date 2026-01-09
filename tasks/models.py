from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
import os

from machines.models import Machine
from core.storages import PrivateMediaStorage


class DowntimeReason(models.Model):
    """
    Predefined reasons for stopping productive work.
    Used to track why operators stop timers and what non-productive time is spent on.
    """
    CATEGORY_CHOICES = [
        ('break', 'Break/Lunch'),
        ('downtime', 'Downtime/Waiting'),
        ('complete', 'Work Complete'),
    ]

    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)

    # Whether this reason should start a new timer automatically
    creates_timer = models.BooleanField(
        default=True,
        help_text="If True, selecting this reason automatically starts a new timer with this reason"
    )

    # Whether this reason requires a reference to a MachineFault
    requires_fault_reference = models.BooleanField(default=False)

    # Display order in UI
    display_order = models.PositiveIntegerField(default=100)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['display_order', 'name']
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"

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

    # Generic relation to Timer model.
    # This allows `task.timers.all()` to work on any BaseTask subclass.
    timers = GenericRelation(
        'tasks.Timer',
        content_type_field='content_type',
        object_id_field='object_id')

    class Meta:
        abstract = True # This is crucial! It means this model won't create a DB table.

    def __str__(self):
        return self.name


class Timer(models.Model):
    """
    Tracks time spent on operations.
    Can be productive work time or non-productive time (breaks, downtime, etc.)
    """
    TIMER_TYPE_CHOICES = [
        ('productive', 'Productive Work'),
        ('break', 'Break/Lunch'),
        ('downtime', 'Downtime'),
    ]

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

    # New fields for downtime tracking
    timer_type = models.CharField(
        max_length=20,
        choices=TIMER_TYPE_CHOICES,
        default='productive',
        db_index=True,
        help_text="Type of time being tracked"
    )

    downtime_reason = models.ForeignKey(
        DowntimeReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='timers',
        help_text="Reason for non-productive time"
    )

    # Optional reference to machine fault if downtime is fault-related
    related_fault = models.ForeignKey(
        'machines.MachineFault',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='downtime_timers',
        help_text="Machine fault that caused this downtime"
    )

    @property
    def can_be_stopped_by_user(self) -> bool:
        """
        Determines if user can manually stop this timer.
        Fault-related timers can only be stopped when the fault is resolved.
        """
        return self.related_fault_id is None

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


class Part(models.Model):
    """
    Represents a physical component to be manufactured.
    This is separate from the legacy Task system.
    """
    key = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    # Legacy task key (for migration from machining.Task)
    # This preserves the original task key that's written on physical drawings
    task_key = models.CharField(max_length=255, null=True, blank=True, db_index=True, unique=True)

    # Job data
    job_no = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    image_no = models.CharField(max_length=255, null=True, blank=True)
    position_no = models.CharField(max_length=255, null=True, blank=True)

    # Quantity & specs
    quantity = models.IntegerField(null=True, blank=True)
    material = models.CharField(max_length=255, null=True, blank=True)
    dimensions = models.CharField(max_length=255, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)

    # Timeline
    finish_time = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts_created')
    created_at = models.BigIntegerField(null=True, blank=True)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='parts_completed')
    completion_date = models.BigIntegerField(null=True, blank=True)

    # File attachments (drawings, specs, etc.)
    files = GenericRelation(
        'tasks.TaskFile',
        content_type_field='content_type',
        object_id_field='object_id'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_no']),
            models.Index(fields=['completion_date']),
        ]

    def __str__(self):
        return f"{self.key} - {self.name}"


class Tool(models.Model):
    """
    Catalog of manufacturing tools with inventory tracking.
    """
    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    category = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    quantity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    properties = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def get_in_use_count(self):
        """Count tools currently in use (operations with active timers)"""
        from django.db.models import Sum
        result = self.tool_operations.filter(
            operation__timers__finish_time__isnull=True  # Active timers only
        ).aggregate(total=Sum('quantity'))
        return result['total'] or 0

    def get_available_quantity(self):
        """Calculate available quantity"""
        return self.quantity - self.get_in_use_count()

    def is_available(self, required_quantity=1):
        """Check if tool is available in required quantity"""
        return self.get_available_quantity() >= required_quantity


class Operation(BaseTask):
    """
    Represents a single work step on a part.
    Inherits from BaseTask to reuse machine assignment, planning fields, timers, etc.
    """
    # Parent relationship
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='operations')

    # Sequencing
    order = models.PositiveIntegerField()
    interchangeable = models.BooleanField(
        default=False,
        help_text="If True, this operation can be completed out of order"
    )

    # Tools (many-to-many via junction)
    tools = models.ManyToManyField(
        Tool,
        through='OperationTool',
        related_name='operations',
        blank=True
    )

    class Meta:
        ordering = ['part', 'order']
        indexes = [
            models.Index(fields=['part', 'order']),
            models.Index(fields=['machine_fk', 'in_plan']),
            models.Index(fields=['machine_fk', 'plan_order']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['part', 'order'],
                name='unique_operation_order_per_part'
            ),
            models.UniqueConstraint(
                fields=['machine_fk', 'plan_order'],
                name='unique_operation_plan_order',
                condition=models.Q(plan_order__isnull=False, in_plan=True)
            ),
        ]

    def __str__(self):
        return f"{self.key} - {self.name}"

    def clean(self):
        """Validate operation order and completion constraints."""
        from django.core.exceptions import ValidationError

        # Validate order constraints on completion
        if self.completion_date and not self.interchangeable:
            # Check if all previous operations are completed
            previous_incomplete = Operation.objects.filter(
                part=self.part,
                order__lt=self.order,
                completion_date__isnull=True
            )
            if previous_incomplete.exists():
                incomplete_orders = list(previous_incomplete.values_list('order', flat=True))
                raise ValidationError(
                    f"Cannot complete operation {self.order}. "
                    f"All previous operations must be completed first: {incomplete_orders}"
                )

    def save(self, *args, **kwargs):
        # Auto-generate key if not set
        if not self.key:
            self.key = f"{self.part.key}-OP-{self.order}"

        # Completed operations must not occupy plan slots
        if self.completion_date is not None:
            self.in_plan = False
            self.plan_order = None

        super().save(*args, **kwargs)

        # Check if all operations are complete -> auto-complete parent part
        if self.completion_date:
            self._check_and_complete_part()

    def _check_and_complete_part(self):
        """Auto-complete parent part if all operations are completed."""
        # Check if all sibling operations are completed
        if not self.part.operations.filter(completion_date__isnull=True).exists():
            # All operations complete -> complete parent part
            if not self.part.completion_date:
                import time
                self.part.completion_date = int(time.time() * 1000)
                self.part.completed_by = self.completed_by
                self.part.save()


class OperationTool(models.Model):
    """
    Junction table for Operation-Tool relationship.
    Allows tracking which tools are required/used for each operation.
    """
    operation = models.ForeignKey(
        Operation,
        on_delete=models.CASCADE,
        related_name='operation_tools'
    )
    tool = models.ForeignKey(
        Tool,
        on_delete=models.PROTECT,  # Prevent deletion of tools in use
        related_name='tool_operations'
    )

    # Quantity needed and usage notes
    quantity = models.PositiveIntegerField(default=1)
    notes = models.TextField(null=True, blank=True)

    # Order for display
    display_order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['operation', 'display_order']
        unique_together = [('operation', 'tool')]

    def __str__(self):
        return f"{self.operation.key} - {self.tool.code} (x{self.quantity})"


# ============================================================================
# COST TRACKING MODELS (Replacing machining.JobCost*)
# ============================================================================

class PartCostAgg(models.Model):
    """
    Aggregated cost for a Part.
    Replaces machining.JobCostAgg.

    Calculates total hours and costs across all operations on this part.
    Hours are broken down by work type: ww (working hours), ah (after hours), su (sunday).
    """
    part = models.OneToOneField(Part, on_delete=models.CASCADE, primary_key=True, related_name='cost_agg')
    job_no_cached = models.CharField(max_length=100, db_index=True, help_text="Cached job_no for filtering")
    currency = models.CharField(max_length=3, default="EUR")

    # Hours by work type
    hours_ww = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Working hours")
    hours_ah = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="After hours")
    hours_su = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Sunday hours")

    # Costs by work type
    cost_ww = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_ah = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_su = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks_partcostagg'
        verbose_name = "Part Cost Aggregate"
        verbose_name_plural = "Part Cost Aggregates"
        indexes = [
            models.Index(fields=['job_no_cached']),
            models.Index(fields=['-total_cost']),
        ]

    def __str__(self):
        return f"{self.part.key} - {self.total_cost} {self.currency}"


class PartCostAggUser(models.Model):
    """
    Per-user cost breakdown for a Part.
    Replaces machining.JobCostAggUser.

    Tracks hours and costs per user per part, broken down by work type.
    """
    part = models.ForeignKey(Part, on_delete=models.CASCADE, related_name='cost_agg_users')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    job_no_cached = models.CharField(max_length=100, db_index=True)
    currency = models.CharField(max_length=3, default="EUR")

    # Hours by work type
    hours_ww = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_ah = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hours_su = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Costs by work type
    cost_ww = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_ah = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    cost_su = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks_partcostaguser'
        verbose_name = "Part Cost Per User"
        verbose_name_plural = "Part Costs Per User"
        unique_together = [('part', 'user')]
        indexes = [
            models.Index(fields=['user']),
            models.Index(fields=['job_no_cached']),
        ]

    def __str__(self):
        return f"{self.part.key} - {self.user.username} - {self.total_cost} {self.currency}"


class PartCostRecalcQueue(models.Model):
    """
    Queue for recalculating part costs.
    Replaces machining.JobCostRecalcQueue.

    When a timer changes on any operation, the parent part is enqueued here.
    A background job processes this queue to recalculate costs.
    """
    part = models.OneToOneField(Part, on_delete=models.CASCADE, primary_key=True)
    enqueued_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks_partcostrecalcqueue'
        verbose_name = "Part Cost Recalc Queue"
        verbose_name_plural = "Part Cost Recalc Queue"

    def __str__(self):
        return f"{self.part.key} - queued at {self.enqueued_at}"
