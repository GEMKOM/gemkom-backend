import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from core.storages import PrivateMediaStorage


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
        ordering = ['code']
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
        default='EUR'
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
            try:
                self.complete(_auto=True)
            except ValueError:
                # May fail if there are incomplete department tasks
                pass

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

    def complete(self, user=None, _auto=False):
        """
        Mark job as completed.

        This method should only be called automatically when all department tasks
        or all children are completed. Manual completion is not allowed.

        Args:
            user: The user completing the job (for auto-completion tracking)
            _auto: Internal flag, must be True. Prevents manual completion.
        """
        if not _auto:
            raise ValueError(
                "İş emirleri manuel olarak tamamlanamaz. "
                "Tüm departman görevleri veya alt işler tamamlandığında otomatik olarak tamamlanır."
            )

        if self.status not in ['active', 'on_hold']:
            raise ValueError("Sadece aktif veya beklemedeki işler tamamlanabilir.")

        has_tasks = self.department_tasks.exists()
        has_children = self.children.exists()

        # Must have either department tasks or children to be completable
        if not has_tasks and not has_children:
            raise ValueError(
                "İş tamamlanamaz: Departman görevi veya alt iş eklenmeli."
            )

        # Check all department tasks are complete (if any exist)
        if has_tasks:
            incomplete_tasks = self.department_tasks.exclude(
                status__in=['completed', 'skipped']
            ).count()
            if incomplete_tasks > 0:
                raise ValueError(
                    f"İş tamamlanamaz: {incomplete_tasks} departman görevi hala bekliyor."
                )

        # Check all children are complete (if any exist)
        if has_children:
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


# =============================================================================
# Job Order Files
# =============================================================================

def job_order_file_upload_path(instance, filename):
    """Upload path for job order attachments."""
    return os.path.join('job_order_files', instance.job_order.job_no, filename)


class JobOrderFile(models.Model):
    """
    File attachment for a job order.
    Can be drawings, specifications, contracts, etc.
    """
    FILE_TYPE_CHOICES = [
        ('drawing', 'Çizim'),
        ('specification', 'Şartname'),
        ('contract', 'Sözleşme'),
        ('correspondence', 'Yazışma'),
        ('photo', 'Fotoğraf'),
        ('other', 'Diğer'),
    ]

    job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(
        upload_to=job_order_file_upload_path,
        storage=PrivateMediaStorage()
    )
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        default='other'
    )
    name = models.CharField(max_length=255, blank=True)  # Display name, auto-filled from filename
    description = models.TextField(blank=True, null=True)

    # Audit
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_job_order_files'
    )

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'İş Emri Dosyası'
        verbose_name_plural = 'İş Emri Dosyaları'

    def __str__(self):
        return f"{self.job_order.job_no} - {self.name or os.path.basename(self.file.name)}"

    def save(self, *args, **kwargs):
        # Auto-fill name from filename if not provided
        if not self.name and self.file:
            self.name = os.path.basename(self.file.name)
        super().save(*args, **kwargs)

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def file_size(self):
        try:
            return self.file.size
        except:
            return None


# =============================================================================
# Department Task Templates
# =============================================================================

DEPARTMENT_CHOICES = [
    ('design', 'Dizayn'),
    ('planning', 'Planlama'),
    ('procurement', 'Satın Alma'),
    ('manufacturing', 'Üretim'),
    ('painting', 'Boya'),
    ('logistics', 'Lojistik'),
]


class DepartmentTaskTemplate(models.Model):
    """
    Reusable template for creating department tasks on job orders.
    Planning team can create/edit these templates.
    """
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='task_templates_created'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Departman Görevi Şablonu'
        verbose_name_plural = 'Departman Görevi Şablonları'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Ensure only one default template
        if self.is_default:
            DepartmentTaskTemplate.objects.filter(is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class DepartmentTaskTemplateItem(models.Model):
    """
    Individual department task within a template.
    Defines which departments in what order with dependencies.
    """
    template = models.ForeignKey(
        DepartmentTaskTemplate,
        on_delete=models.CASCADE,
        related_name='items'
    )
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES)
    title = models.CharField(max_length=255, blank=True)  # Auto-filled from department if empty
    sequence = models.PositiveIntegerField(default=1)

    # Dependencies - this task can start when these are done
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependents'
    )

    class Meta:
        ordering = ['template', 'sequence']
        unique_together = [('template', 'department')]
        verbose_name = 'Şablon Öğesi'
        verbose_name_plural = 'Şablon Öğeleri'

    def __str__(self):
        return f"{self.template.name} - {self.get_department_display()}"

    def save(self, *args, **kwargs):
        # Auto-fill title from department display name if not provided
        if not self.title:
            self.title = self.get_department_display()
        super().save(*args, **kwargs)


# =============================================================================
# Job Order Department Tasks
# =============================================================================

class JobOrderDepartmentTask(models.Model):
    """
    Department-specific task within a job order.
    Can have subtasks for detailed tracking.
    """
    STATUS_CHOICES = [
        ('pending', 'Bekliyor'),
        ('in_progress', 'Devam Ediyor'),
        ('completed', 'Tamamlandı'),
        ('skipped', 'Atlandı'),
    ]

    job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.CASCADE,
        related_name='department_tasks'
    )
    department = models.CharField(
        max_length=50,
        choices=DEPARTMENT_CHOICES,
        db_index=True
    )

    # Hierarchical - main tasks have no parent, subtasks have parent
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='subtasks'
    )

    # Task details
    title = models.CharField(max_length=255, blank=True)  # Auto-filled from job_order.title
    description = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    # Assignment
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_department_tasks'
    )

    # Timeline
    target_start_date = models.DateField(null=True, blank=True)
    target_completion_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Dependencies - task can start when these tasks are completed
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependents'
    )

    # Order/sequence within job (for main tasks)
    sequence = models.PositiveIntegerField(default=1)

    # Notes
    notes = models.TextField(blank=True, null=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='department_tasks_created'
    )
    updated_at = models.DateTimeField(auto_now=True)
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='department_tasks_completed'
    )

    class Meta:
        ordering = ['job_order', 'sequence']
        indexes = [
            models.Index(fields=['department', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['job_order', 'parent']),
        ]
        verbose_name = 'Departman Görevi'
        verbose_name_plural = 'Departman Görevleri'

    def __str__(self):
        if self.parent:
            return f"{self.job_order.job_no} - {self.parent.title} - {self.title}"
        return f"{self.job_order.job_no} - {self.title}"

    def save(self, *args, **kwargs):
        # Auto-fill title from job order if not provided
        if not self.title and self.job_order_id:
            self.title = self.job_order.title
        super().save(*args, **kwargs)

    def can_start(self):
        """Check if all dependencies are completed."""
        return not self.depends_on.exclude(status__in=['completed', 'skipped']).exists()

    def start(self, user=None):
        """Start working on this task."""
        if self.status != 'pending':
            raise ValueError("Sadece bekleyen görevler başlatılabilir.")

        if not self.can_start():
            raise ValueError("Bağımlı görevler henüz tamamlanmadı.")

        self.status = 'in_progress'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

        # Update job order status to active if still draft
        if self.job_order.status == 'draft':
            self.job_order.start(user=user)

    def complete(self, user=None):
        """Mark task as completed."""
        if self.status != 'in_progress':
            raise ValueError("Sadece devam eden görevler tamamlanabilir.")

        # For main tasks: check all subtasks are complete
        if not self.parent:
            incomplete_subtasks = self.subtasks.exclude(status__in=['completed', 'skipped']).count()
            if incomplete_subtasks > 0:
                raise ValueError(
                    f"Alt görevler tamamlanmadan ana görev tamamlanamaz: {incomplete_subtasks} alt görev bekliyor."
                )

        self.status = 'completed'
        self.completed_at = timezone.now()
        self.completed_by = user
        self.save(update_fields=['status', 'completed_at', 'completed_by'])

        # If this is a subtask, check if parent can auto-complete
        if self.parent:
            self.parent._check_subtask_completion(user)

        # Update job order completion percentage
        self.job_order.update_completion_percentage()

        # Check if all main tasks are complete -> auto-complete job order
        self._check_job_order_completion(user)

    def _check_subtask_completion(self, user):
        """Check if all subtasks are done and auto-complete parent if so."""
        if self.subtasks.exclude(status__in=['completed', 'skipped']).exists():
            return

        # All subtasks done - auto-complete parent
        if self.status == 'in_progress':
            self.complete(user)

    def _check_job_order_completion(self, user):
        """Check if all main department tasks are complete and auto-complete job order."""
        # Only check for main tasks (no parent)
        if self.parent:
            return

        # Check if all main tasks are complete
        incomplete_main_tasks = self.job_order.department_tasks.filter(
            parent__isnull=True
        ).exclude(status__in=['completed', 'skipped']).count()

        if incomplete_main_tasks == 0 and self.job_order.status == 'active':
            try:
                self.job_order.complete(user=user, _auto=True)
            except ValueError:
                # Job order might have other constraints (children, etc.)
                pass

    def skip(self, user=None):
        """Mark task as skipped (not applicable)."""
        if self.status == 'completed':
            raise ValueError("Tamamlanmış görevler atlanamaz.")

        self.status = 'skipped'
        self.completed_at = timezone.now()
        self.completed_by = user
        self.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Update job order completion percentage
        self.job_order.update_completion_percentage()

        # Check if all main tasks are complete -> auto-complete job order
        self._check_job_order_completion(user)

    def uncomplete(self):
        """Revert a completed task back to in_progress."""
        if self.status != 'completed':
            raise ValueError("Sadece tamamlanmış görevler geri alınabilir.")

        # If this is a subtask and parent was auto-completed, revert parent first
        if self.parent and self.parent.status == 'completed':
            self.parent.uncomplete()

        self.status = 'in_progress'
        self.completed_at = None
        self.completed_by = None
        self.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Revert job order if it was auto-completed
        if self.job_order.status == 'completed':
            self.job_order.status = 'active'
            self.job_order.completed_at = None
            self.job_order.completed_by = None
            self.job_order.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Update job order completion percentage
        self.job_order.update_completion_percentage()
