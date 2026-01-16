from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal


CURRENCY_CHOICES = [
    ('TRY', 'Türk Lirası'),
    ('USD', 'Amerikan Doları'),
    ('EUR', 'Euro'),
    ('GBP', 'İngiliz Sterlini'),
]


class Customer(models.Model):
    """
    Customer/client entity for job orders.
    Separate model to enable relationship history and reporting.
    """
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    # Tax and billing
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    tax_office = models.CharField(max_length=100, blank=True, null=True)

    # Preferred terms
    default_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='TRY'
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Notes
    notes = models.TextField(blank=True, null=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customers_created'
    )
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = 'Müşteri'
        verbose_name_plural = 'Müşteriler'

    def __str__(self):
        if self.short_name:
            return f"{self.code} - {self.short_name}"
        return f"{self.code} - {self.name}"


class JobOrder(models.Model):
    """
    Central job order tracking entity.
    Represents a project or work order from customer.
    Supports hierarchical structure (parent-child jobs).
    """
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('active', 'Aktif'),
        ('on_hold', 'Beklemede'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal Edildi'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Düşük'),
        ('normal', 'Normal'),
        ('high', 'Yüksek'),
        ('urgent', 'Acil'),
    ]

    # Job identification (hierarchical)
    # Format: "254-01" (parent), "254-01-01" (child), "254-01-01-01" (grandchild)
    job_no = models.CharField(max_length=50, unique=True, primary_key=True, db_index=True)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )

    # Basic info
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='job_orders'
    )
    customer_order_no = models.CharField(max_length=100, blank=True, null=True)

    # Status and priority
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal'
    )

    # Timeline
    target_completion_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Cost tracking (calculated periodically)
    estimated_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0.00')
    )
    labor_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0.00')
    )
    material_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0.00')
    )
    subcontractor_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal('0.00')
    )
    cost_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='TRY'
    )
    last_cost_calculation = models.DateTimeField(null=True, blank=True)

    # Progress tracking (auto-calculated from department tasks)
    completion_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_orders_created'
    )
    updated_at = models.DateTimeField(auto_now=True)
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_orders_completed'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['target_completion_date']),
        ]
        verbose_name = 'İş Emri'
        verbose_name_plural = 'İş Emirleri'

    def __str__(self):
        return f"{self.job_no} - {self.title}"

    def get_hierarchy_level(self):
        """Calculate depth: 254-01 = 0, 254-01-01 = 1, etc."""
        return self.job_no.count('-') - 1

    def get_all_children(self):
        """Get all descendants recursively."""
        children = list(self.children.all())
        for child in self.children.all():
            children.extend(child.get_all_children())
        return children

    def update_completion_percentage(self):
        """Calculate completion based on department task progress."""
        dept_tasks = self.department_tasks.all()
        if not dept_tasks.exists():
            self.completion_percentage = Decimal('0.00')
        else:
            completed = dept_tasks.filter(status='completed').count()
            skipped = dept_tasks.filter(status='skipped').count()
            total = dept_tasks.count() - skipped
            if total > 0:
                self.completion_percentage = Decimal((completed / total) * 100).quantize(Decimal('0.01'))
            else:
                self.completion_percentage = Decimal('100.00')

        self.save(update_fields=['completion_percentage'])

        # Update parent if exists
        if self.parent:
            self.parent.update_completion_from_children()

    def update_completion_from_children(self):
        """Update completion based on children progress (for parent jobs)."""
        if not self.children.exists():
            return

        # Average of children completion
        from django.db.models import Avg
        child_avg = self.children.aggregate(avg=Avg('completion_percentage'))['avg'] or Decimal('0.00')
        self.completion_percentage = Decimal(child_avg).quantize(Decimal('0.01'))
        self.save(update_fields=['completion_percentage'])

        # Recursively update parent
        if self.parent:
            self.parent.update_completion_from_children()

    def update_status_from_children(self):
        """Cascading status: if all children completed, mark self completed."""
        if not self.children.exists():
            return

        all_completed = all(
            child.status == 'completed'
            for child in self.children.all()
        )
        if all_completed and self.status == 'active':
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.completion_percentage = Decimal('100.00')
            self.save(update_fields=['status', 'completed_at', 'completion_percentage'])

            # Recursively check parent
            if self.parent:
                self.parent.update_status_from_children()

    def start(self, user=None):
        """Transition from draft to active. Cascades to all children."""
        if self.status != 'draft':
            raise ValueError("Sadece taslak durumundaki işler başlatılabilir.")
        self.status = 'active'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

        # Cascade to children
        for child in self.children.filter(status='draft'):
            child.start(user=user)

    def complete(self, user=None):
        """Mark job as completed."""
        if self.status not in ['active', 'on_hold']:
            raise ValueError("Sadece aktif veya beklemedeki işler tamamlanabilir.")

        # Check all department tasks are complete (if any exist)
        incomplete_tasks = self.department_tasks.exclude(
            status__in=['completed', 'skipped']
        ).count()
        if incomplete_tasks > 0:
            raise ValueError(
                f"İş tamamlanamaz: {incomplete_tasks} departman görevi hala bekliyor."
            )

        # Check all children are complete (if any exist)
        incomplete_children = self.children.exclude(status='completed').count()
        if incomplete_children > 0:
            raise ValueError(
                f"İş tamamlanamaz: {incomplete_children} alt iş hala tamamlanmadı."
            )

        self.status = 'completed'
        self.completed_at = timezone.now()
        self.completed_by = user
        self.completion_percentage = Decimal('100.00')
        self.save(update_fields=['status', 'completed_at', 'completed_by', 'completion_percentage'])

        # Update parent status if all siblings complete
        if self.parent:
            self.parent.update_status_from_children()

    def hold(self, reason=""):
        """Put job on hold. Cascades to all children."""
        if self.status != 'active':
            raise ValueError("Sadece aktif işler beklemeye alınabilir.")
        self.status = 'on_hold'
        self.save(update_fields=['status'])

        # Cascade to children
        for child in self.children.filter(status='active'):
            child.hold(reason=reason)

    def resume(self):
        """Resume from hold. Cascades to all children."""
        if self.status != 'on_hold':
            raise ValueError("Sadece beklemedeki işler devam ettirilebilir.")
        self.status = 'active'
        self.save(update_fields=['status'])

        # Cascade to children
        for child in self.children.filter(status='on_hold'):
            child.resume()

    def cancel(self, user=None):
        """Cancel the job order. Cascades to all children."""
        if self.status == 'completed':
            raise ValueError("Tamamlanmış işler iptal edilemez.")
        self.status = 'cancelled'
        self.save(update_fields=['status'])

        # Cascade to children (except completed ones)
        for child in self.children.exclude(status='completed'):
            child.cancel(user=user)
