from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericRelation
from approvals.models import ApprovalWorkflow


# Fixed procurement item code covering every crane/platform rental (accounting reference).
PROCUREMENT_ITEM_CODE = "730.10.005"


class CraneType(models.Model):
    """Catalog of rentable cranes and lift platforms (the price-list rows)."""

    CATEGORY_CHOICES = [
        ('basket_crane', 'Sepetli Vinç'),
        ('truck_crane', 'Kamyon Üstü Vinç'),
        ('mobile_crane', 'Mobil Vinç'),
        ('scissor_platform', 'Makaslı Platform'),
        ('articulated_platform', 'Eklemli Platform'),
    ]

    PLATFORM_CATEGORIES = ('scissor_platform', 'articulated_platform')

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name

    @property
    def is_platform(self):
        return self.category in self.PLATFORM_CATEGORIES

    def current_rate(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return self.rates.filter(effective_from__lte=on_date).order_by('-effective_from').first()


class CraneRate(models.Model):
    """
    Versioned price records per crane type (pattern: users.WageRate).
    The 'current' rate is the one with the latest effective_from not in the future.
    Price updates create new rows; history is never mutated.
    """

    CURRENCY_CHOICES = [
        ("TRY", "TRY"),
        ("USD", "USD"),
        ("EUR", "EUR"),
    ]

    crane_type = models.ForeignKey(CraneType, on_delete=models.PROTECT, related_name='rates')
    effective_from = models.DateField(db_index=True)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")

    # Cranes: bracket prices. Null = bracket not offered (e.g. 52 Mt has no 3h price).
    price_up_to_3h = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_up_to_8h = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Platforms: daily price + round-trip transport fee.
    price_per_day = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    transport_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Cranes: flat fee for an extra rigger (ilave sapancı).
    rigger_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    note = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ['-effective_from']
        constraints = [
            models.UniqueConstraint(fields=["crane_type", "effective_from"], name="uniq_crane_rate_effective_from"),
        ]
        indexes = [
            models.Index(fields=["crane_type", "effective_from"]),
        ]

    def __str__(self):
        return f"{self.crane_type.name} @ {self.effective_from} ({self.currency})"


class CraneRequest(models.Model):
    """
    A department's request to rent a crane/platform for a specific job.
    Approved by the requester's department manager (approvals engine),
    then arranged by the coordination team, who record actual hours/cost
    at completion — the actual cost flows into job costs.
    """

    STATUS_CHOICES = [
        ('submitted', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('cancelled', 'İptal Edildi'),
        ('completed', 'Tamamlandı'),
    ]

    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('urgent', 'Acil'),
        ('critical', 'Kritik'),
    ]

    PRICING_OPTION_CHOICES = [
        ('up_to_3h', '3 Saate Kadar'),
        ('up_to_8h', '8 Saate Kadar'),
        ('daily', 'Günlük'),
    ]

    request_number = models.CharField(max_length=50, unique=True)
    requestor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='crane_requests')
    department = models.CharField(max_length=100)  # Auto-set; drives department-head approver selection

    # One specific job per request. CharField, not FK: the job dropdown includes the
    # synthetic '1000 – Fabrika İşleri' entry which has no JobOrder row.
    job_no = models.CharField(max_length=50, db_index=True)

    crane_type = models.ForeignKey(CraneType, on_delete=models.PROTECT, related_name='requests')
    pricing_option = models.CharField(max_length=10, choices=PRICING_OPTION_CHOICES)
    days = models.PositiveIntegerField(default=1)  # Only meaningful for pricing_option='daily'
    needs_rigger = models.BooleanField(default=False)

    needed_date = models.DateField(default=timezone.localdate)
    needed_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')

    # Cost estimate snapshot, computed server-side at create from the current rate.
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    estimated_cost_currency = models.CharField(max_length=3, default='TRY')
    estimate_breakdown = models.JSONField(default=dict, blank=True)

    # Actuals — mandatory at completion; the actual cost feeds job costs.
    actual_quantity = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Fiili saat (vinç) veya gün (platform)",
    )
    actual_cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    actual_cost_currency = models.CharField(max_length=3, default='TRY')
    completed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='completed_crane_requests'
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    # Approval tracking
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_crane_requests'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    approvals = GenericRelation(ApprovalWorkflow, related_query_name="crane_request")
    files = GenericRelation(
        'planning.FileAttachment',
        content_type_field='content_type',
        object_id_field='object_id',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['department', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['job_no', 'status']),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.crane_type.name} ({self.job_no})"

    def save(self, *args, **kwargs):
        if not self.request_number:
            last_request = CraneRequest.objects.order_by('-id').first()
            if last_request:
                last_number = int(last_request.request_number.split('-')[-1])
                self.request_number = f"CR-{timezone.now().year}-{last_number + 1:04d}"
            else:
                self.request_number = f"CR-{timezone.now().year}-0001"
        super().save(*args, **kwargs)
