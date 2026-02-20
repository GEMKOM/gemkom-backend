from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum

CURRENCY_CHOICES = [
    ('TRY', 'TRY'),
    ('EUR', 'EUR'),
    ('USD', 'USD'),
    ('GBP', 'GBP'),
]


class Subcontractor(models.Model):
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50, blank=True)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField(max_length=50, blank=True)
    tax_office = models.CharField(max_length=100, blank=True)
    bank_info = models.TextField(blank=True)
    agreement_details = models.TextField(blank=True)
    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subcontractors_created'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Taşeron'
        verbose_name_plural = 'Taşeronlar'

    def __str__(self):
        return self.name


class SubcontractingPriceTier(models.Model):
    """
    Planning sets one or more price tiers on a job order.
    Each tier defines a price_per_kg for a specific weight allocation.
    Multiple tiers allow different rates for different parts of the same job.
    """
    job_order = models.ForeignKey(
        'projects.JobOrder',
        on_delete=models.CASCADE,
        related_name='subcontracting_price_tiers'
    )
    name = models.CharField(max_length=200, help_text='e.g. "Ağır Plakalar", "Hafif Çerçeve"')
    price_per_kg = models.DecimalField(
        max_digits=12, decimal_places=4,
        validators=[MinValueValidator(Decimal('0'))]
    )
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')
    allocated_weight_kg = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['job_order', 'id']
        verbose_name = 'Taşeron Fiyat Kademesi'
        verbose_name_plural = 'Taşeron Fiyat Kademeleri'

    def __str__(self):
        return f"{self.job_order_id} – {self.name} ({self.price_per_kg} {self.currency}/kg)"

    @property
    def used_weight_kg(self) -> Decimal:
        """Total weight already assigned to subtasks for this tier."""
        result = self.subtask_assignments.aggregate(total=Sum('allocated_weight_kg'))['total']
        return result or Decimal('0.00')

    @property
    def remaining_weight_kg(self) -> Decimal:
        """Weight still available for new assignments."""
        return self.allocated_weight_kg - self.used_weight_kg


class SubcontractingAssignment(models.Model):
    """
    Links a manufacturing department subtask to a subcontractor and a price tier.
    Cost = allocated_weight_kg × (delta_progress / 100) × price_per_kg
    where delta_progress = current progress - last_billed_progress.

    last_billed_progress is updated each time a statement including this
    assignment is approved, locking in the "paid up to" baseline.
    """
    department_task = models.OneToOneField(
        'projects.JobOrderDepartmentTask',
        on_delete=models.CASCADE,
        related_name='subcontracting_assignment'
    )
    subcontractor = models.ForeignKey(
        Subcontractor,
        on_delete=models.PROTECT,
        related_name='assignments'
    )
    price_tier = models.ForeignKey(
        SubcontractingPriceTier,
        on_delete=models.PROTECT,
        related_name='subtask_assignments'
    )
    allocated_weight_kg = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # Cached total cost (allocated_weight_kg × current_progress/100 × price_per_kg).
    # Represents the CUMULATIVE cost so far (not just the unbilled delta).
    current_cost = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    cost_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')

    # The progress (0-100) at which the last approved statement was cut.
    # New statements will only bill the delta: current_progress - last_billed_progress.
    last_billed_progress = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['subcontractor']),
            models.Index(fields=['price_tier']),
        ]
        verbose_name = 'Taşeron Ataması'
        verbose_name_plural = 'Taşeron Atamaları'

    def __str__(self):
        return (
            f"{self.department_task.job_order_id} – "
            f"{self.subcontractor.name} – "
            f"{self.allocated_weight_kg}kg"
        )

    def recalculate_cost(self):
        """
        Recalculate and cache the cumulative cost from current progress.
        This does NOT advance last_billed_progress — that happens only on statement approval.
        """
        progress = self.department_task.manual_progress or Decimal('0')
        self.current_cost = (
            self.allocated_weight_kg
            * (progress / Decimal('100'))
            * self.price_tier.price_per_kg
        ).quantize(Decimal('0.01'))
        self.cost_currency = self.price_tier.currency

    @property
    def current_progress(self) -> Decimal:
        return self.department_task.manual_progress or Decimal('0')

    @property
    def unbilled_progress(self) -> Decimal:
        """Progress not yet covered by an approved statement."""
        return max(Decimal('0'), self.current_progress - self.last_billed_progress)

    @property
    def unbilled_cost(self) -> Decimal:
        """Cost for the unbilled progress delta."""
        return (
            self.allocated_weight_kg
            * (self.unbilled_progress / Decimal('100'))
            * self.price_tier.price_per_kg
        ).quantize(Decimal('0.01'))


class SubcontractorCostRecalcQueue(models.Model):
    """
    Queue for background subcontractor cost recalculation per job order.
    Processed by DrainSubcontractorCostQueueView.
    """
    job_no = models.CharField(max_length=50, primary_key=True)
    enqueued_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subcontracting_cost_recalc_queue'

    def __str__(self):
        return self.job_no


class SubcontractorStatement(models.Model):
    """
    Monthly payment document for a subcontractor.

    Line items capture only the DELTA progress since the previous approved
    statement, so each statement represents only new, unbilled work.

    On approval, last_billed_progress is advanced on all linked assignments.
    """
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('submitted', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('paid', 'Ödendi'),
        ('cancelled', 'İptal Edildi'),
    ]

    subcontractor = models.ForeignKey(
        Subcontractor,
        on_delete=models.PROTECT,
        related_name='statements'
    )
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')

    # Calculated totals (refreshed when line items / adjustments change)
    work_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    adjustment_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    grand_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))

    notes = models.TextField(blank=True)

    # Approval engine hook — uses GenericForeignKey in ApprovalWorkflow
    approvals = GenericRelation('approvals.ApprovalWorkflow')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('subcontractor', 'year', 'month')]
        ordering = ['-year', '-month']
        verbose_name = 'Taşeron Hakedişi'
        verbose_name_plural = 'Taşeron Hakedişleri'

    def __str__(self):
        return f"{self.subcontractor.name} – {self.year}/{self.month:02d}"

    def recalculate_totals(self):
        self.work_total = (
            self.line_items.aggregate(total=Sum('cost_amount'))['total'] or Decimal('0.00')
        )
        self.adjustment_total = (
            self.adjustments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        )
        self.grand_total = self.work_total + self.adjustment_total

    def handle_approval_event(self, workflow, event, payload):
        """
        Called by the approvals engine after a decision.
        Status is set by the caller (approval_service.decide_statement).
        On approval, we advance last_billed_progress on all assignments.
        """
        pass  # Logic handled in approval_service.decide_statement


class SubcontractorStatementLine(models.Model):
    """
    Snapshot of a single assignment's DELTA cost at statement generation time.

    Stores both the previous (already-billed) progress and the current progress
    so that cost_amount = allocated_weight_kg × (delta/100) × price_per_kg,
    representing only the new work since the last approved statement.
    """
    statement = models.ForeignKey(
        SubcontractorStatement,
        on_delete=models.CASCADE,
        related_name='line_items'
    )
    assignment = models.ForeignKey(
        SubcontractingAssignment,
        on_delete=models.PROTECT,
        related_name='statement_lines'
    )

    # Denormalized for reporting (immutable after creation)
    job_no = models.CharField(max_length=50)
    job_title = models.CharField(max_length=255, blank=True)
    subcontractor_name = models.CharField(max_length=200)
    price_tier_name = models.CharField(max_length=200)

    # Snapshot values at statement generation
    allocated_weight_kg = models.DecimalField(max_digits=12, decimal_places=2)
    previous_progress = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='last_billed_progress at time of statement generation (already paid)'
    )
    current_progress = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='manual_progress at time of statement generation'
    )
    delta_progress = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='current_progress - previous_progress (what is being billed)'
    )
    effective_weight_kg = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text='allocated_weight_kg × delta_progress / 100'
    )
    price_per_kg = models.DecimalField(max_digits=12, decimal_places=4)
    cost_amount = models.DecimalField(
        max_digits=16, decimal_places=2,
        help_text='effective_weight_kg × price_per_kg'
    )

    class Meta:
        ordering = ['job_no', 'id']
        verbose_name = 'Hakediş Kalemi'
        verbose_name_plural = 'Hakediş Kalemleri'

    def __str__(self):
        return f"{self.statement} – {self.job_no} {self.delta_progress}%"


class SubcontractorStatementAdjustment(models.Model):
    """
    Manual addition or deduction on a statement.
    Positive amount = extra payment, negative amount = deduction.
    """
    ADJUSTMENT_TYPE_CHOICES = [
        ('addition', 'Ek Ödeme'),
        ('deduction', 'Kesinti'),
    ]

    statement = models.ForeignKey(
        SubcontractorStatement,
        on_delete=models.CASCADE,
        related_name='adjustments'
    )
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPE_CHOICES)
    amount = models.DecimalField(
        max_digits=16, decimal_places=2,
        help_text='Positive for additions, negative for deductions'
    )
    reason = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    job_order = models.ForeignKey(
        'projects.JobOrder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        ordering = ['id']
        verbose_name = 'Hakediş Düzeltmesi'
        verbose_name_plural = 'Hakediş Düzeltmeleri'

    def __str__(self):
        return f"{self.statement} – {self.get_adjustment_type_display()} {self.amount}"
