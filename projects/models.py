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
    quantity = models.PositiveIntegerField(default=1)
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
    incoterms = models.CharField(null=True, blank=True)

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
        """
        Calculate completion based on department task progress using nested weights.

        For procurement tasks:
            - Progress comes from PlanningRequestItem procurement status
            - Uses item unit_weight × quantity_to_purchase for weighting

        For tasks with subtasks:
            - Task contributes: (completed_subtask_weight / total_subtask_weight) * task_weight
            - Skipped subtasks are excluded from calculation

        For tasks without subtasks:
            - Completed task contributes its full weight
            - Pending/in_progress contributes 0

        Skipped main tasks are excluded from the total weight calculation.
        """
        from django.db.models import Sum

        # Only count main tasks (no parent), excluding skipped and cancelled
        main_tasks = self.department_tasks.filter(parent__isnull=True).exclude(status__in=['skipped', 'cancelled'])

        if not main_tasks.exists():
            self.completion_percentage = Decimal('0.00')
        else:
            total_weight = Decimal('0.00')
            earned_weight = Decimal('0.00')

            for task in main_tasks:
                task_weight = Decimal(task.weight)
                total_weight += task_weight

                if task.department == 'procurement':
                    # Procurement-specific: use PlanningRequestItem progress
                    pr_earned, pr_total = task.get_procurement_progress()
                    if pr_total > 0:
                        task_progress = pr_earned / pr_total
                        earned_weight += task_progress * task_weight
                    elif task.status == 'completed':
                        # No items to procure but task is complete
                        earned_weight += task_weight
                else:
                    # Check if task has subtasks (exclude skipped and cancelled)
                    subtasks = task.subtasks.exclude(status__in=['skipped', 'cancelled'])

                    if subtasks.exists():
                        # Nested calculation: use subtask weights with special handling
                        subtask_total_weight = Decimal('0')
                        subtask_earned_weight = Decimal('0')

                        for subtask in subtasks:
                            subtask_weight = Decimal(subtask.weight)
                            subtask_total_weight += subtask_weight

                            # Handle CNC Kesim subtask specially
                            if subtask.title == 'CNC Kesim':
                                cnc_earned, cnc_total = subtask.get_cnc_progress()
                                if cnc_total > 0:
                                    subtask_progress = cnc_earned / cnc_total
                                    subtask_earned_weight += subtask_progress * subtask_weight
                                elif subtask.status == 'completed':
                                    subtask_earned_weight += subtask_weight
                            # Handle Talaşlı İmalat subtask specially
                            elif subtask.title == 'Talaşlı İmalat':
                                machining_earned, machining_total = subtask.get_machining_progress()
                                if machining_total > 0:
                                    subtask_progress = machining_earned / machining_total
                                    subtask_earned_weight += subtask_progress * subtask_weight
                                elif subtask.status == 'completed':
                                    subtask_earned_weight += subtask_weight
                            elif subtask.status == 'completed':
                                subtask_earned_weight += subtask_weight

                        if subtask_total_weight > 0:
                            # Proportional contribution based on subtask completion
                            earned_weight += (subtask_earned_weight / subtask_total_weight) * task_weight
                        elif task.status == 'completed':
                            # No non-skipped subtasks but task is complete
                            earned_weight += task_weight
                    else:
                        # No subtasks: use manual_progress or status
                        if task.status == 'completed':
                            earned_weight += task_weight
                        elif task.manual_progress > 0:
                            earned_weight += (task.manual_progress / Decimal('100')) * task_weight

            if total_weight > 0:
                self.completion_percentage = (
                    (earned_weight / total_weight) * 100
                ).quantize(Decimal('0.01'))
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
        """Put job on hold. Cascades to all children and department tasks."""
        if self.status != 'active':
            raise ValueError("Sadece aktif işler beklemeye alınabilir.")
        self.status = 'on_hold'
        self.save(update_fields=['status'])

        # Cascade to children
        for child in self.children.filter(status='active'):
            child.hold(reason=reason)

        # Cascade to department tasks (put in_progress tasks on hold)
        self.department_tasks.filter(status='in_progress').update(status='on_hold')

    def resume(self):
        """Resume from hold. Cascades to all children and department tasks."""
        if self.status != 'on_hold':
            raise ValueError("Sadece beklemedeki işler devam ettirilebilir.")
        self.status = 'active'
        self.save(update_fields=['status'])

        # Cascade to children
        for child in self.children.filter(status='on_hold'):
            child.resume()

        # Cascade to department tasks (resume on_hold tasks back to in_progress)
        self.department_tasks.filter(status='on_hold').update(status='in_progress')

    def cancel(self, user=None):
        """Cancel the job order. Cascades to all children and department tasks."""
        if self.status == 'completed':
            raise ValueError("Tamamlanmış işler iptal edilemez.")
        self.status = 'cancelled'
        self.save(update_fields=['status'])

        # Cascade to children (except completed ones)
        for child in self.children.exclude(status='completed'):
            child.cancel(user=user)

        # Cascade to department tasks (cancel non-completed/skipped tasks)
        self.department_tasks.exclude(
            status__in=['completed', 'skipped']
        ).update(status='cancelled')


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
    Supports hierarchy - main tasks have no parent, subtasks have parent.
    """
    template = models.ForeignKey(
        DepartmentTaskTemplate,
        on_delete=models.CASCADE,
        related_name='items'
    )
    department = models.CharField(max_length=50, choices=DEPARTMENT_CHOICES)
    title = models.CharField(max_length=255, blank=True)  # Auto-filled from department if empty
    sequence = models.PositiveIntegerField(default=1)

    # Weight for progress calculation (default: 10 points)
    # Higher weight = more impact on completion percentage
    weight = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Görev ağırlığı (1-100 puan). Varsayılan: 10'
    )

    # Hierarchical - main items have no parent, sub-items have parent
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )

    # Dependencies - this task can start when these are done (only for main items)
    depends_on = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='dependents'
    )

    class Meta:
        ordering = ['template', 'sequence']
        verbose_name = 'Şablon Öğesi'
        verbose_name_plural = 'Şablon Öğeleri'

    def __str__(self):
        if self.parent:
            return f"{self.template.name} - {self.parent.title} - {self.title}"
        return f"{self.template.name} - {self.title or self.get_department_display()}"

    def save(self, *args, **kwargs):
        # Auto-fill title from department display name if not provided (for main items)
        if not self.title and not self.parent:
            self.title = self.get_department_display()
        # Inherit department from parent if this is a child item
        if self.parent:
            self.department = self.parent.department
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
        ('blocked', 'Engellenmiş'),
        ('in_progress', 'Devam Ediyor'),
        ('on_hold', 'Askıda'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal Edildi'),
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

    # Weight for progress calculation (default: 10 points)
    weight = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Görev ağırlığı (1-100 puan). Varsayılan: 10'
    )

    # Manual progress for regular tasks (0-100)
    manual_progress = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
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
        """
        Check if task can be started.
        - Main tasks: check if all dependencies are completed
        - Subtasks: check if parent is not blocked
        """
        # For subtasks, parent must not be blocked
        if self.parent and self.parent.status == 'blocked':
            return False

        # Check own dependencies
        return not self.depends_on.exclude(status__in=['completed', 'skipped']).exists()

    def update_status_from_dependencies(self):
        """
        Update task status based on dependency completion.
        - If dependencies are incomplete or parent is blocked: set to 'blocked'
        - If all dependencies are complete and parent allows: set to 'in_progress'
        Updates pending, blocked, or in_progress tasks.
        Cascades status changes to subtasks.
        """
        # Don't update completed or skipped tasks
        if self.status in ['completed', 'skipped']:
            return

        old_status = self.status

        if self.can_start():
            # All dependencies complete - transition to in_progress
            if self.status != 'in_progress':
                self.status = 'in_progress'
                if not self.started_at:
                    self.started_at = timezone.now()
                self.save(update_fields=['status', 'started_at'])
        else:
            # Dependencies incomplete - ensure it's blocked
            if self.status != 'blocked':
                self.status = 'blocked'
                self.save(update_fields=['status'])

        # If status changed, update all subtasks
        if old_status != self.status and not self.parent:
            for subtask in self.subtasks.all():
                subtask.update_status_from_dependencies()

    def start(self, user=None):
        """Start working on this task."""
        if self.status not in ['pending', 'blocked']:
            raise ValueError("Sadece bekleyen veya engellenmiş görevler başlatılabilir.")

        # For subtasks, check if parent is blocked
        if self.parent and self.parent.status == 'blocked':
            raise ValueError("Üst görev engellenmiş olduğu için bu alt görev başlatılamaz.")

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

        # For subtasks: ensure parent is not blocked
        if self.parent and self.parent.status == 'blocked':
            raise ValueError("Üst görev engellenmiş olduğu için bu alt görev tamamlanamaz.")

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

        # Update all dependent tasks - check if they can now start
        for dependent_task in self.dependents.all():
            dependent_task.update_status_from_dependencies()

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

        # For subtasks: ensure parent is not blocked
        if self.parent and self.parent.status == 'blocked':
            raise ValueError("Üst görev engellenmiş olduğu için bu alt görev atlanamaz.")

        self.status = 'skipped'
        self.completed_at = timezone.now()
        self.completed_by = user
        self.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Update all dependent tasks - check if they can now start
        for dependent_task in self.dependents.all():
            dependent_task.update_status_from_dependencies()

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

        # Update all dependent tasks - they may need to be blocked again
        for dependent_task in self.dependents.filter(status='in_progress'):
            dependent_task.update_status_from_dependencies()

        # Revert job order if it was auto-completed
        if self.job_order.status == 'completed':
            self.job_order.status = 'active'
            self.job_order.completed_at = None
            self.job_order.completed_by = None
            self.job_order.save(update_fields=['status', 'completed_at', 'completed_by'])

        # Update job order completion percentage
        self.job_order.update_completion_percentage()

    def get_procurement_progress(self):
        """
        Calculate progress for procurement tasks based on PlanningRequestItem status.
        Returns (earned_weight, total_weight) tuple.

        Progress stages per item:
        - 0%: No PurchaseRequestItem exists
        - 40%: PurchaseRequestItem exists (PR submitted)
        - 50%: PurchaseRequest approved
        - 100%: PurchaseOrder fully paid
        """
        if self.department != 'procurement':
            return (Decimal('0.00'), Decimal('0.00'))

        from planning.models import PlanningRequestItem

        # Get all planning request items for this job that need procurement
        pr_items = PlanningRequestItem.objects.filter(
            job_no=self.job_order.job_no,
            quantity_to_purchase__gt=0
        ).select_related('item')

        if not pr_items.exists():
            return (Decimal('0.00'), Decimal('0.00'))

        total_weight = Decimal('0.00')
        earned_weight = Decimal('0.00')

        for item in pr_items:
            earned, total = item.get_procurement_progress()
            total_weight += total
            earned_weight += earned

        return (earned_weight, total_weight)

    def check_auto_complete(self, user=None):
        """
        Check if procurement task should auto-complete.
        Returns True if auto-completed, False otherwise.
        """
        if self.department != 'procurement':
            return False

        if self.status != 'in_progress':
            return False

        earned, total = self.get_procurement_progress()
        if total > 0 and earned >= total:
            # All items at 100%
            self.complete(user=user)
            return True
        return False

    def get_cnc_progress(self):
        """
        Calculate progress for CNC Kesim subtask based on CncPart completion.

        Returns: (earned_weight, total_weight)

        Progress:
        - 0%: No CncPart for this job, OR CncTask not complete
        - 100%: CncPart exists AND CncTask.completion_date is set
        """
        if self.title != 'CNC Kesim':
            return (Decimal('0.00'), Decimal('0.00'))

        from cnc_cutting.models import CncPart

        # Get all CncParts for this job
        cnc_parts = CncPart.objects.filter(
            job_no=self.job_order.job_no
        ).select_related('cnc_task')

        if not cnc_parts.exists():
            return (Decimal('0.00'), Decimal('0.00'))

        total_weight = Decimal('0.00')
        earned_weight = Decimal('0.00')

        for part in cnc_parts:
            part_weight = (part.weight_kg or Decimal('0')) * (part.quantity or 1)
            total_weight += part_weight

            # Only count if CncTask is completed
            if part.cnc_task.completion_date is not None:
                earned_weight += part_weight

        return (earned_weight, total_weight)

    def check_cnc_auto_complete(self, user=None):
        """
        Check if CNC Kesim subtask should auto-complete.
        Returns True if auto-completed, False otherwise.
        """
        if self.title != 'CNC Kesim':
            return False

        if self.status != 'in_progress':
            return False

        earned, total = self.get_cnc_progress()
        if total > 0 and earned >= total:
            self.complete(user=user)
            return True
        return False

    def get_machining_progress(self):
        """
        Calculate progress for Talaşlı İmalat subtask based on Operation hour tracking.

        Returns: (earned_hours, total_estimated_hours)

        Uses existing fields:
        - Operation.estimated_hours (stored field)
        - total_hours_spent (calculated via queryset annotation from timers)

        Progress per Operation = min(total_hours_spent / estimated_hours, 1.0)
        Aggregate: sum all operation progress weighted by estimated_hours
        """
        if self.title != 'Talaşlı İmalat':
            return (Decimal('0.00'), Decimal('0.00'))

        from tasks.models import Operation
        from django.db.models import Sum, Q, ExpressionWrapper, FloatField, Value
        from django.db.models.functions import Coalesce

        # Get all operations for parts with this job_no
        operations = Operation.objects.filter(
            part__job_no=self.job_order.job_no
        ).annotate(
            # Calculate total_hours_spent using same logic as OperationViewSet
            total_hours_spent=Coalesce(
                ExpressionWrapper(
                    Sum('timers__finish_time', filter=Q(timers__finish_time__isnull=False)) -
                    Sum('timers__start_time', filter=Q(timers__finish_time__isnull=False)),
                    output_field=FloatField()
                ) / 3600000.0,
                Value(0.0)
            )
        )

        total_estimated = Decimal('0.00')
        earned_hours = Decimal('0.00')

        for op in operations:
            if not op.estimated_hours or op.estimated_hours <= 0:
                # Skip operations with no estimate
                continue

            estimated = Decimal(str(op.estimated_hours))
            total_estimated += estimated

            # Completed operations are 100% regardless of hours spent
            if op.completion_date is not None:
                earned_hours += estimated
                continue

            # Get hours spent (already annotated)
            spent = Decimal(str(op.total_hours_spent))

            # Calculate progress for this operation (capped at 100%)
            progress = min(spent / estimated, Decimal('1.0'))
            earned_hours += progress * estimated

        return (earned_hours, total_estimated)

    def check_machining_auto_complete(self, user=None):
        """
        Check if Talaşlı İmalat subtask should auto-complete.
        Auto-completes only when ALL parts for this job order have completion_date set.
        Returns True if auto-completed, False otherwise.
        """
        if self.title != 'Talaşlı İmalat':
            return False

        if self.status != 'in_progress':
            return False

        from tasks.models import Part
        parts = Part.objects.filter(job_no=self.job_order.job_no)
        if parts.exists() and not parts.filter(completion_date__isnull=True).exists():
            self.complete(user=user)
            return True
        return False

    def get_completion_percentage(self, skip_expensive_calculations=False):
        """
        Calculate completion percentage for this department task.

        For CNC Kesim tasks: based on CNC part completion
        For procurement tasks: based on procurement progress
        For tasks with subtasks: based on subtask completion
        For simple tasks: 0% or 100% based on status

        Args:
            skip_expensive_calculations: If True, skip CNC/machining progress queries
                                       and return approximate values for in_progress tasks
        """
        from decimal import Decimal

        # Completed tasks are 100%
        if self.status == 'completed':
            return Decimal('100.00')

        # Skipped tasks are considered 100%
        if self.status == 'skipped':
            return Decimal('100.00')

        # Cancelled tasks are 0%
        if self.status == 'cancelled':
            return Decimal('0.00')

        # Special tasks (CNC, Machining, Procurement) calculate real progress
        # even when blocked/pending, since underlying work happens independently
        is_special_task = (
            self.title in ['CNC Kesim', 'Talaşlı İmalat']
            or self.department == 'procurement'
        )

        if is_special_task:
            if skip_expensive_calculations:
                return Decimal('50.00')

            if self.title == 'CNC Kesim':
                earned, total = self.get_cnc_progress()
                if total > 0:
                    return ((earned / total) * 100).quantize(Decimal('0.01'))
                return Decimal('0.00')

            if self.title == 'Talaşlı İmalat':
                earned, total = self.get_machining_progress()
                if total > 0:
                    return ((earned / total) * 100).quantize(Decimal('0.01'))
                return Decimal('0.00')

            if self.department == 'procurement':
                earned, total = self.get_procurement_progress()
                if total > 0:
                    return ((earned / total) * 100).quantize(Decimal('0.01'))
                return Decimal('0.00')

        # Pending/blocked tasks (non-special) are 0%
        if self.status in ['pending', 'blocked']:
            return Decimal('0.00')

        # In-progress tasks - calculate based on type

        # For nested serializers, skip expensive calculations and return approximation
        if skip_expensive_calculations:
            # For tasks with subtasks, try quick calculation using only status
            if hasattr(self, '_prefetched_objects_cache') and 'subtasks' in self._prefetched_objects_cache:
                subtasks = self.subtasks.all()
            else:
                # Use count-based query instead of fetching all subtasks
                from django.db.models import Count, Q
                counts = self.subtasks.aggregate(
                    total=Count('id', filter=~Q(status='skipped')),
                    completed=Count('id', filter=Q(status='completed'))
                )
                if counts['total'] > 0:
                    return (Decimal(str(counts['completed'])) / Decimal(str(counts['total'])) * 100).quantize(Decimal('0.01'))
                return self.manual_progress

            # If subtasks were prefetched, use them
            if subtasks.exists():
                total_count = 0
                completed_count = 0
                for subtask in subtasks:
                    if subtask.status != 'skipped':
                        total_count += 1
                        if subtask.status == 'completed':
                            completed_count += 1

                if total_count > 0:
                    return (Decimal(str(completed_count)) / Decimal(str(total_count)) * 100).quantize(Decimal('0.01'))

            return self.manual_progress

        # Full calculation (for detail views)

        # Tasks with subtasks - calculate based on subtask completion
        subtasks = self.subtasks.all()
        if subtasks.exists():
            total_weight = Decimal('0.00')
            earned_weight = Decimal('0.00')

            for subtask in subtasks:
                # Skip skipped and cancelled subtasks in the calculation
                if subtask.status in ['skipped', 'cancelled']:
                    continue

                subtask_weight = Decimal(str(subtask.weight))
                total_weight += subtask_weight

                # Recursively get subtask completion (also skip expensive calculations)
                subtask_percentage = subtask.get_completion_percentage(skip_expensive_calculations=skip_expensive_calculations)
                earned_weight += (subtask_percentage / 100) * subtask_weight

            if total_weight > 0:
                return ((earned_weight / total_weight) * 100).quantize(Decimal('0.01'))
            return Decimal('0.00')

        # Simple tasks without subtasks - use manual_progress
        return self.manual_progress


def discussion_attachment_upload_path(instance, filename):
    """Upload path: discussion_files/{job_no}/{topic_id}/{filename}"""
    topic = instance.topic or instance.comment.topic
    job_no = topic.job_order.job_no
    topic_id = topic.id
    return f'discussion_files/{job_no}/{topic_id}/{filename}'


class JobOrderDiscussionTopic(models.Model):
    """Discussion topic for main job orders."""

    PRIORITY_CHOICES = [
        ('low', 'Düşük'),
        ('normal', 'Normal'),
        ('high', 'Önemli'),
        ('urgent', 'Çok Önemli'),
    ]

    TOPIC_TYPE_CHOICES = [
        ('general', 'Genel'),
        ('drawing_release', 'Çizim Yayını'),
        ('revision_request', 'Revizyon Talebi'),
    ]

    REVISION_STATUS_CHOICES = [
        ('pending', 'Onay Bekliyor'),
        ('in_progress', 'Devam Ediyor'),
        ('resolved', 'Çözüldü'),
        ('rejected', 'Reddedildi'),
    ]

    # Core fields
    job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.CASCADE,
        related_name='discussion_topics',
        limit_choices_to={'parent__isnull': True}
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        db_index=True
    )

    # Topic type for special workflows
    topic_type = models.CharField(
        max_length=20,
        choices=TOPIC_TYPE_CHOICES,
        default='general',
        db_index=True
    )

    # For revision requests
    revision_status = models.CharField(
        max_length=20,
        choices=REVISION_STATUS_CHOICES,
        null=True,
        blank=True,
        db_index=True
    )
    revision_assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_revision_requests'
    )
    related_release = models.ForeignKey(
        'TechnicalDrawingRelease',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='revision_topics'
    )

    # Ownership
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='discussion_topics_created'
    )

    # @mentions
    mentioned_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='discussion_topics_mentioned_in'
    )

    # Edit tracking
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft delete
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='discussion_topics_deleted'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job_order', 'is_deleted']),
            models.Index(fields=['created_by', 'created_at']),
            models.Index(fields=['priority', 'created_at']),
        ]

    def extract_mentions(self):
        """Extract @username mentions."""
        import re
        pattern = r'@(\w+)'
        usernames = re.findall(pattern, self.content)
        users = User.objects.filter(username__in=usernames)
        return users

    def get_comment_count(self):
        return self.comments.filter(is_deleted=False).count()

    def get_participant_count(self):
        commenter_ids = self.comments.filter(
            is_deleted=False
        ).values_list('created_by_id', flat=True).distinct()
        participants = set(commenter_ids)
        if self.created_by_id:
            participants.add(self.created_by_id)
        return len(participants)


class JobOrderDiscussionComment(models.Model):
    """Comment within a discussion topic."""

    topic = models.ForeignKey(
        JobOrderDiscussionTopic,
        on_delete=models.CASCADE,
        related_name='comments'
    )
    content = models.TextField()

    # Ownership
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='discussion_comments_created'
    )

    # @mentions
    mentioned_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='discussion_comments_mentioned_in'
    )

    # Edit tracking
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft delete
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='discussion_comments_deleted'
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['topic', 'is_deleted', 'created_at']),
            models.Index(fields=['created_by', 'created_at']),
        ]

    def extract_mentions(self):
        """Extract @username mentions."""
        import re
        pattern = r'@(\w+)'
        usernames = re.findall(pattern, self.content)
        users = User.objects.filter(username__in=usernames)
        return users


class DiscussionAttachment(models.Model):
    """File attachment for discussions."""

    topic = models.ForeignKey(
        JobOrderDiscussionTopic,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments'
    )
    comment = models.ForeignKey(
        JobOrderDiscussionComment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='attachments'
    )
    file = models.FileField(
        upload_to=discussion_attachment_upload_path,
        storage=PrivateMediaStorage()
    )
    name = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='discussion_attachments_uploaded'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def save(self, *args, **kwargs):
        if self.file:
            self.name = self.file.name
            self.size = self.file.size
        super().save(*args, **kwargs)


class DiscussionNotification(models.Model):
    """Track notifications for discussions."""

    NOTIFICATION_TYPE_CHOICES = [
        ('topic_mention', 'Konuda Etiketlendi'),
        ('comment_mention', 'Yorumda Etiketlendi'),
        ('new_comment', 'Yeni Yorum'),
        ('drawing_released', 'Çizim Yayınlandı'),
        ('revision_requested', 'Revizyon Talep Edildi'),
        ('revision_approved', 'Revizyon Onaylandı'),
        ('revision_completed', 'Revizyon Tamamlandı'),
        ('revision_rejected', 'Revizyon Reddedildi'),
        ('job_on_hold', 'İş Beklemede'),
        ('job_resumed', 'İş Devam Ediyor'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='discussion_notifications'
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPE_CHOICES,
        db_index=True
    )

    topic = models.ForeignKey(
        JobOrderDiscussionTopic,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )
    comment = models.ForeignKey(
        JobOrderDiscussionComment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )

    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    is_emailed = models.BooleanField(default=False)
    emailed_at = models.DateTimeField(null=True, blank=True)
    email_error = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['user', 'notification_type', 'created_at']),
        ]
        unique_together = [
            ('user', 'topic', 'comment', 'notification_type')
        ]

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class TechnicalDrawingRelease(models.Model):
    """Tracks technical drawing releases for a job order."""

    STATUS_CHOICES = [
        ('released', 'Yayınlandı'),
        ('in_revision', 'Revizyon Yapılıyor'),
        ('superseded', 'Güncelliğini Kaybetti'),
    ]

    job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.CASCADE,
        related_name='technical_drawing_releases'
    )

    # Version tracking
    revision_number = models.PositiveIntegerField(default=1)
    revision_code = models.CharField(max_length=10, blank=True)  # e.g., "A1", "B2"

    # Folder path (network path to drawings)
    folder_path = models.CharField(max_length=500)

    # Release details
    changelog = models.TextField(blank=True, help_text='Değişiklik açıklaması')
    hardcopy_count = models.PositiveIntegerField(default=0, help_text='Hardcopy set sayısı')

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='released',
        db_index=True
    )

    # Who released
    released_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='drawing_releases'
    )
    released_at = models.DateTimeField(auto_now_add=True)

    # Link to discussion topic announcing this release
    release_topic = models.OneToOneField(
        JobOrderDiscussionTopic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drawing_release'
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-revision_number']
        unique_together = [('job_order', 'revision_number')]
        indexes = [
            models.Index(fields=['job_order', 'status']),
        ]
        verbose_name = 'Teknik Çizim Yayını'
        verbose_name_plural = 'Teknik Çizim Yayınları'

    def __str__(self):
        return f"{self.job_order.job_no} - Rev.{self.revision_number}"

    @staticmethod
    def get_next_revision_number(job_order):
        """Get the next revision number for a job order."""
        latest = TechnicalDrawingRelease.objects.filter(
            job_order=job_order
        ).order_by('-revision_number').first()
        return (latest.revision_number + 1) if latest else 1

    @staticmethod
    def get_current_release(job_order):
        """Get the latest active release for a job order."""
        return TechnicalDrawingRelease.objects.filter(
            job_order=job_order,
            status='released'
        ).order_by('-revision_number').first()
