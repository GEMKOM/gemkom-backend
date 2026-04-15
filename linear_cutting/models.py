from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from machines.models import Machine
from tasks.models import BaseTask, TaskKeyCounter


def _next_session_key():
    counter, _ = TaskKeyCounter.objects.get_or_create(prefix='LC')
    counter.current += 1
    counter.save(update_fields=['current'])
    return f"LC-{counter.current:04d}"


class LinearCuttingSession(models.Model):
    """
    One optimization run for a set of parts to be cut from stock bars.
    Contains the input parameters and stores the optimization result.
    """
    key = models.CharField(max_length=20, primary_key=True)
    title = models.CharField(max_length=255)
    material = models.CharField(
        max_length=100,
        help_text="Material / profile description, e.g. 'S235 IPE200'"
    )
    stock_length_mm = models.IntegerField(
        help_text="Standard stock bar length in mm, e.g. 6000"
    )
    kerf_mm = models.DecimalField(
        max_digits=5, decimal_places=2, default=3,
        help_text="Saw blade kerf (material lost per cut) in mm"
    )
    notes = models.TextField(blank=True)

    # Optimization result snapshot (populated by /optimize/ endpoint)
    bars_needed = models.IntegerField(null=True, blank=True)
    total_waste_mm = models.IntegerField(null=True, blank=True)
    efficiency_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    optimization_result = models.JSONField(
        null=True, blank=True,
        help_text="Full optimization layout JSON for display without re-running"
    )

    # Workflow flags
    tasks_created = models.BooleanField(default=False)
    planning_request_created = models.BooleanField(default=False)

    # Audit
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='linear_cutting_sessions'
    )
    created_at = models.BigIntegerField(null=True, blank=True, help_text="Epoch ms")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.key} – {self.title}"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = _next_session_key()
        super().save(*args, **kwargs)


class LinearCuttingPart(models.Model):
    """
    One part type entered by the user for a cutting session.
    A part with quantity=5 means 5 identical pieces of that length.
    """
    session = models.ForeignKey(
        LinearCuttingSession, on_delete=models.CASCADE, related_name='parts'
    )
    label = models.CharField(max_length=255, help_text="Part name / description")
    job_no = models.CharField(
        max_length=255, blank=True,
        help_text="Optional job order number this part belongs to"
    )
    nominal_length_mm = models.IntegerField(help_text="Required cut length in mm")
    quantity = models.IntegerField(help_text="Number of pieces needed")
    angle_left_deg = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Miter angle on the left end in degrees (0 = square cut)"
    )
    angle_right_deg = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Miter angle on the right end in degrees (0 = square cut)"
    )
    profile_height_mm = models.IntegerField(
        default=0,
        help_text="Profile height in mm, used to calculate extra material consumed by angle cuts"
    )
    order = models.PositiveIntegerField(default=0, help_text="Display order in the UI")

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.label} {self.nominal_length_mm}mm ×{self.quantity} ({self.session.key})"


class LinearCuttingTask(BaseTask):
    """
    One stock bar to be cut. Created per bar from the optimization result.
    Workers start timers on these tasks when they begin cutting a bar.
    """
    session = models.ForeignKey(
        LinearCuttingSession, on_delete=models.CASCADE, related_name='cutting_tasks'
    )
    bar_index = models.PositiveIntegerField(help_text="Bar number within the session (1-based)")
    stock_length_mm = models.IntegerField()
    material = models.CharField(max_length=100)
    layout_json = models.JSONField(
        help_text="Array of cuts on this bar: [{label, nominal_mm, effective_mm, offset_mm}]"
    )
    waste_mm = models.IntegerField(default=0)

    # Generic relation so task.timers.all() works (inherited via BaseTask)
    issue_key = GenericRelation(
        'tasks.Timer',
        content_type_field='content_type',
        object_id_field='object_id',
    )

    def __str__(self):
        return f"{self.key} – Bar {self.bar_index} of {self.session.key}"

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = f"{self.session.key}-B{self.bar_index}"
        if self.completion_date is not None:
            self.in_plan = False
            self.plan_order = None
        super().save(*args, **kwargs)
