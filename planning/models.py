from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.contrib.contenttypes.fields import GenericRelation, GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from approvals.models import ApprovalWorkflow
from core.storages import PrivateMediaStorage
import os
import uuid


# Helper function for file upload paths
def attachment_upload_path(instance, filename):
    """
    Centralized upload path for shared file assets.
    Spreads files by date to avoid huge flat folders.
    """
    today = timezone.now().date()
    return os.path.join(
        'attachments',
        str(today.year),
        f"{today.month:02d}",
        f"{uuid.uuid4()}_{filename}",
    )


class DepartmentRequest(models.Model):
    """
    Simple pre-procurement request from departments (maintenance, etc.)
    Needs department head approval before being transferred to Planning.
    Planning maps these to actual catalog items via PlanningRequest.
    """
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('submitted', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('transferred', 'Satın Almaya Aktarıldı'),
        ('cancelled', 'İptal Edildi'),
    ]

    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('urgent', 'Acil'),
        ('critical', 'Kritik'),
    ]

    # Basic Information
    request_number = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    department = models.CharField(max_length=100)  # Used to auto-select department head approvers
    needed_date = models.DateField(default=timezone.localdate)

    # Items as JSON - flexible structure
    items = models.JSONField(default=list, blank=True)

    # Request Details
    requestor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='department_requests')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # Approval tracking
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_department_requests'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Generic relation for approval workflow
    approvals = GenericRelation(
        ApprovalWorkflow,
        related_query_name="department_request",
    )

    # Generic relation for file attachments
    files = GenericRelation(
        'planning.FileAttachment',
        content_type_field='content_type',
        object_id_field='object_id'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['department', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.request_number} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.request_number:
            # Auto-generate request number
            last_request = DepartmentRequest.objects.order_by('-id').first()
            if last_request:
                last_number = int(last_request.request_number.split('-')[-1])
                self.request_number = f"DR-{timezone.now().year}-{last_number + 1:04d}"
            else:
                self.request_number = f"DR-{timezone.now().year}-0001"
        super().save(*args, **kwargs)


class PlanningRequest(models.Model):
    """
    Planning-mapped procurement request.
    Created by Planning team from approved DepartmentRequests.
    Planning maps raw item descriptions to actual catalog Items.
    Each line represents a single item+job combination.
    Procurement converts these to PurchaseRequests with offers.
    """
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('ready', 'Satın Almaya Hazır'),
        ('converted', 'Onaya Gönderildi'),
        ('cancelled', 'İptal Edildi'),
    ]

    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('urgent', 'Acil'),
        ('critical', 'Kritik'),
    ]

    # Basic Information
    request_number = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    needed_date = models.DateField(default=timezone.now)

    # Source tracking
    department_request = models.ForeignKey(
        DepartmentRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='planning_requests'
    )

    # Request Details
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_planning_requests'
    )
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)  # when marked ready for procurement
    converted_at = models.DateTimeField(null=True, blank=True)

    # Removed: Link to the resulting PR (when converted)
    # This is now a many-to-many relationship on the PurchaseRequest side

    class Meta:
        ordering = ['-created_at']

    # Generic relation for file attachments
    files = GenericRelation(
        'planning.FileAttachment',
        content_type_field='content_type',
        object_id_field='object_id'
    )
    
    indexes = [
        models.Index(fields=['status', 'created_at']),
        models.Index(fields=['created_by', 'status']),
    ]

    def __str__(self):
        return f"{self.request_number} - {self.title}"

    def save(self, *args, **kwargs):
        if not self.request_number:
            # Auto-generate request number
            last_request = PlanningRequest.objects.order_by('-id').first()
            if last_request:
                last_number = int(last_request.request_number.split('-')[-1])
                self.request_number = f"PLR-{timezone.now().year}-{last_number + 1:04d}"
            else:
                self.request_number = f"PLR-{timezone.now().year}-0001"
        super().save(*args, **kwargs)


class PlanningRequestItem(models.Model):
    """
    Individual item line in a PlanningRequest.
    Each row = one catalog Item for one job_no.
    Planning creates these by mapping DepartmentRequest raw items to catalog Items.
    """
    planning_request = models.ForeignKey(
        PlanningRequest,
        on_delete=models.CASCADE,
        related_name='items'
    )

    # Mapped catalog item (created/selected by Planning)
    item = models.ForeignKey(
        'procurement.Item',
        on_delete=models.CASCADE,
        related_name='planning_requests'
    )

    # Job allocation
    job_no = models.CharField(max_length=50)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )

    # Priority & specs (can override parent or be item-specific)
    priority = models.CharField(
        max_length=20,
        choices=PlanningRequest.PRIORITY_CHOICES,
        default='normal'
    )
    specifications = models.TextField(blank=True)

    # Optional: track which DepartmentRequest item this came from
    source_item_index = models.PositiveIntegerField(null=True, blank=True)  # index in DR.items JSON

    # Ordering
    order = models.PositiveIntegerField(default=0)

    # Generic relation for file attachments (mapped from DepartmentRequest files or new uploads)
    files = GenericRelation(
        'planning.FileAttachment',
        content_type_field='content_type',
        object_id_field='object_id'
    )

    class Meta:
        ordering = ['planning_request', 'order']

    def __str__(self):
        return f"{self.item.code} - {self.job_no} - {self.quantity}"


class FileAsset(models.Model):
    """
    Physical file stored once. Can be linked to any request/item via FileAttachment.
    """
    file = models.FileField(upload_to=attachment_upload_path, storage=PrivateMediaStorage())
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, help_text="Optional description of the file")

    def __str__(self):
        return os.path.basename(self.file.name)


class FileAttachment(models.Model):
    """
    Lightweight link between a FileAsset and any target object (DR, PR, PRI).
    Allows the same asset to be visible in multiple contexts without duplicating the file.
    """
    asset = models.ForeignKey(
        FileAsset,
        on_delete=models.CASCADE,
        related_name='attachments'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=255, blank=True, help_text="Optional description of the file")

    # Optional reference to original attachment if this was mapped from another request
    source_attachment = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mapped_attachments',
        help_text="Original attachment if this was mapped from another request/item",
    )

    # Generic Foreign Key to link to any model (DepartmentRequest, PlanningRequest, PlanningRequestItem)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    attached_to = GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
        ]

    @property
    def file(self):
        """Convenience access to the stored file."""
        return self.asset.file

    def __str__(self):
        return f"Attachment to {self.content_type} #{self.object_id} - {os.path.basename(self.asset.file.name)}"
