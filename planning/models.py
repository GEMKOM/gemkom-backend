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
    Sanitizes filename to avoid S3 compatibility issues.
    """
    import re
    import unicodedata

    # Sanitize filename: remove/replace problematic characters
    # Remove leading @ or special chars that can cause S3 issues
    name, ext = os.path.splitext(filename)

    # Transliterate Turkish and other Unicode characters to ASCII
    # This handles: Ç->C, İ->I, Ş->S, Ğ->G, Ü->U, Ö->O, etc.
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')

    # Remove leading special characters
    name = re.sub(r'^[@#$%^&*]+', '', name)

    # Replace problematic characters with underscores
    # Keep only: ASCII letters, numbers, spaces, dash, underscore, dot
    name = re.sub(r'[^a-zA-Z0-9\s\-._]', '_', name)

    # Replace multiple spaces/underscores with single underscore
    name = re.sub(r'[\s_]+', '_', name)

    # Remove leading/trailing underscores
    name = name.strip('_')

    # Reconstruct filename
    sanitized_filename = f"{name}{ext}"

    today = timezone.now().date()
    return os.path.join(
        'attachments',
        str(today.year),
        f"{today.month:02d}",
        f"{uuid.uuid4()}_{sanitized_filename}",
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

    Status flow:
    - pending_inventory: Waiting for inventory control (only when check_inventory=True)
    - pending_erp_entry: Inventory control completed, waiting for planning to enter items into ERP
    - ready: Ready for procurement to select
      * Initial status if check_inventory=False (planning handles ERP externally)
      * From pending_erp_entry after ERP entry completed
    - converted: Converted to purchase request and sent for approval
    - completed: All items fulfilled from inventory (no procurement needed)
    - cancelled: Cancelled
    """
    STATUS_CHOICES = [
        ('pending_inventory', 'Stok Kontrolü Bekliyor'),
        ('pending_erp_entry', 'ERP Girişi Bekliyor'),
        ('ready', 'Satın Almaya Hazır'),
        ('converted', 'Onaya Gönderildi'),
        ('completed', 'Tamamlandı'),
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
    erp_code = models.CharField(
        max_length=100,
        blank=True,
        help_text="ERP system code entered by planning team before marking ready for procurement"
    )

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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ready')

    # Inventory control
    check_inventory = models.BooleanField(
        default=False,
        help_text="Whether to check and allocate from inventory"
    )
    inventory_control_completed = models.BooleanField(
        default=False,
        help_text="True when inventory control process is completed"
    )
    fully_from_inventory = models.BooleanField(
        default=False,
        help_text="True if all items were fulfilled from inventory"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ready_at = models.DateTimeField(null=True, blank=True)  # when marked ready for procurement
    converted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)  # when all items are fulfilled

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
        is_new = self.pk is None

        if not self.request_number:
            # Auto-generate request number
            last_request = PlanningRequest.objects.order_by('-id').first()
            if last_request:
                last_number = int(last_request.request_number.split('-')[-1])
                self.request_number = f"GR-{timezone.now().year}-{last_number + 1:04d}"
            else:
                self.request_number = f"GR-{timezone.now().year}-0001"

        # Set initial status based on check_inventory
        if is_new:
            if self.check_inventory:
                self.status = 'pending_inventory'
            else:
                # No inventory control - planning handles ERP entry externally, go directly to ready
                self.status = 'ready'
                self.ready_at = timezone.now()

        super().save(*args, **kwargs)

    def get_completion_stats(self):
        """
        Calculate completion statistics for this planning request.
        Returns dict with total_items, converted_items, and completion_percentage.
        """
        total_items = self.items.count()
        if total_items == 0:
            return {
                'total_items': 0,
                'converted_items': 0,
                'completion_percentage': 0
            }

        # Count items that have been converted to purchase requests
        converted_items = self.items.filter(
            purchase_requests__isnull=False
        ).distinct().count()

        completion_percentage = round((converted_items / total_items) * 100, 2) if total_items > 0 else 0

        return {
            'total_items': total_items,
            'converted_items': converted_items,
            'completion_percentage': completion_percentage
        }

    def check_and_update_completion_status(self):
        """
        Check if all items are fulfilled and update status to 'completed' if needed.

        An item is considered fulfilled if either:
        1. quantity_to_purchase = 0 (fully from inventory), OR
        2. Has at least one approved purchase request

        Returns True if status was updated to completed.
        """
        if self.status == 'completed':
            return False

        items = self.items.all()
        if not items.exists():
            return False

        # Check if all items are fulfilled
        all_fulfilled = True
        for item in items:
            # Item is fulfilled if quantity_to_purchase is 0 (from inventory)
            if item.quantity_to_purchase == Decimal('0.00'):
                continue

            # Or if it has at least one approved purchase request
            if item.purchase_requests.filter(status='approved').exists():
                continue

            # If neither condition is met, item is not fulfilled
            all_fulfilled = False
            break

        if all_fulfilled:
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.save(update_fields=['status', 'completed_at'])
            return True

        return False

    def complete_inventory_control(self):
        """
        Mark inventory control as completed and update status.
        Called when planning team confirms inventory control is done.

        Logic:
        - If ALL items fulfilled from inventory → status='completed', fully_from_inventory=True
        - If SOME/NO items from inventory → status='pending_erp_entry' (waiting for ERP entry)

        Returns dict with status info.
        """
        if not self.check_inventory:
            raise ValueError("Cannot complete inventory control for request without check_inventory enabled.")

        if self.status not in ['pending_inventory']:
            raise ValueError(f"Cannot complete inventory control for request with status '{self.status}'.")

        items = self.items.all()
        if not items.exists():
            raise ValueError("Cannot complete inventory control for request without items.")

        # Check if all items are fully from inventory
        all_from_inventory = all(item.is_fully_from_inventory for item in items)

        self.inventory_control_completed = True

        if all_from_inventory:
            # All items fulfilled from inventory - mark as completed
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.fully_from_inventory = True
            self.save(update_fields=['status', 'completed_at', 'fully_from_inventory', 'inventory_control_completed'])

            return {
                'status': 'completed',
                'message': 'All items fulfilled from inventory. Planning request completed.',
                'fully_from_inventory': True
            }
        else:
            # Some items need purchasing - mark as pending ERP entry
            self.status = 'pending_erp_entry'
            self.fully_from_inventory = False
            self.save(update_fields=['status', 'fully_from_inventory', 'inventory_control_completed'])

            return {
                'status': 'pending_erp_entry',
                'message': 'Inventory control completed. Planning request waiting for ERP entry.',
                'fully_from_inventory': False
            }

    def mark_ready_for_procurement(self, erp_code, request_number=None):
        """
        Mark planning request as ready for procurement after ERP entry.
        Called by planning team after entering items into ERP system.

        Args:
            erp_code: The ERP system code/reference for this request
            request_number: Optional custom request number to set

        Returns dict with status info.
        """
        if self.status not in ['pending_erp_entry']:
            raise ValueError(f"Cannot mark as ready. Planning request status is '{self.status}'. Must be 'pending_erp_entry'.")

        if not erp_code or not erp_code.strip():
            raise ValueError("ERP code is required to mark request as ready for procurement.")

        update_fields = ['erp_code', 'status', 'ready_at']

        if request_number:
            self.request_number = request_number.strip()
            update_fields.append('request_number')

        self.erp_code = erp_code.strip()
        self.status = 'ready'
        self.ready_at = timezone.now()
        self.save(update_fields=update_fields)

        return {
            'status': 'ready',
            'message': 'Planning request marked as ready for procurement.',
            'request_number': self.request_number,
            'erp_code': self.erp_code
        }


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

    # Inventory allocation tracking
    quantity_from_inventory = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Quantity allocated from inventory"
    )
    quantity_to_purchase = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Quantity that needs to be purchased"
    )

    # Original item description from DepartmentRequest
    item_description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Original item name/description from department request (e.g., 'Bearing X123 for Machine Y')"
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
        parts = [self.item.code, self.job_no, str(self.quantity)]

        # Add item name/description if available
        if hasattr(self.item, 'name') and self.item.name:
            parts.append(self.item.name)

        # Add specifications if available
        if self.specifications:
            # Truncate specs if too long (max 50 chars)
            specs = self.specifications[:50] + '...' if len(self.specifications) > 50 else self.specifications
            parts.append(f"[{specs}]")

        if self.item_description:
            # Truncate specs if too long (max 50 chars)
            specs = self.item_description[:50] + '...' if len(self.item_description) > 50 else self.item_description
            parts.append(f"[{specs}]")

        return " - ".join(parts)

    def save(self, *args, **kwargs):
        """
        Auto-calculate quantity_to_purchase based on inventory control setting.
        If check_inventory is False, all quantity needs to be purchased.
        If check_inventory is True, quantity_to_purchase = quantity - quantity_from_inventory
        """
        if self.planning_request_id:
            # Get planning request to check inventory control setting
            if not self.planning_request.check_inventory:
                # No inventory control - all quantity needs to be purchased
                self.quantity_to_purchase = self.quantity
            else:
                # With inventory control - calculate remaining to purchase
                self.quantity_to_purchase = self.quantity - self.quantity_from_inventory

        super().save(*args, **kwargs)

    @property
    def is_converted(self):
        """Check if this planning request item has been fully converted to purchase requests"""
        return self.quantity_remaining_for_purchase <= Decimal('0.00')

    @property
    def is_partially_converted(self):
        """Check if this planning request item has been partially converted to purchase requests"""
        qty_in_prs = self.quantity_in_active_prs
        return qty_in_prs > Decimal('0.00') and qty_in_prs < self.quantity_to_purchase

    @property
    def quantity_in_active_prs(self):
        """
        Sum of quantities in active (non-rejected/cancelled) PurchaseRequestItems.
        This tracks how much of quantity_to_purchase has been converted.
        """
        from django.db.models import Sum, Q

        # Get sum from PurchaseRequestItems that link back to this PlanningRequestItem
        result = self.purchase_request_items.exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).aggregate(total=Sum('quantity'))

        return result['total'] or Decimal('0.00')

    @property
    def quantity_remaining_for_purchase(self):
        """
        Quantity still available for new purchase requests.
        This is quantity_to_purchase minus what's already in active PRs.
        """
        remaining = self.quantity_to_purchase - self.quantity_in_active_prs
        return max(remaining, Decimal('0.00'))

    @property
    def is_available_for_purchase(self):
        """
        Check if this item is available for use in a new purchase request.
        An item is available if it has remaining quantity to convert.
        """
        return self.quantity_remaining_for_purchase > Decimal('0.00')

    @property
    def is_fully_from_inventory(self):
        """Check if this item is fully fulfilled from inventory"""
        return self.quantity_from_inventory >= self.quantity

    @property
    def is_partially_from_inventory(self):
        """Check if this item is partially fulfilled from inventory"""
        return self.quantity_from_inventory > Decimal('0.00') and self.quantity_from_inventory < self.quantity

    @property
    def total_weight(self):
        """Total weight = quantity_to_purchase × item.unit_weight"""
        if self.item and self.quantity_to_purchase:
            return self.quantity_to_purchase * self.item.unit_weight
        return Decimal('0.00')

    def get_procurement_progress(self):
        """
        Calculate procurement progress for this item.

        Returns: (earned_weight, total_weight)

        Progress stages:
        - 0%: No PurchaseRequestItem exists
        - 40%: PurchaseRequestItem exists (PR submitted)
        - 50%: PurchaseRequest approved
        - 100%: PurchaseOrder fully paid
        """
        total = self.total_weight
        if total == Decimal('0.00'):
            return (Decimal('0.00'), Decimal('0.00'))

        # Get all PurchaseRequestItems for this PlanningRequestItem
        pr_items = self.purchase_request_items.select_related(
            'purchase_request'
        ).prefetch_related(
            'po_lines__po'
        )

        if not pr_items.exists():
            return (Decimal('0.00'), total)

        # Calculate weighted progress
        earned = Decimal('0.00')

        for pri in pr_items:
            item_weight = pri.quantity * self.item.unit_weight
            pr_status = pri.purchase_request.status

            if pr_status in ('cancelled', 'rejected'):
                # Doesn't count
                continue

            # Check if PO exists and is paid
            po_lines = pri.po_lines.all()
            if po_lines.exists():
                # Check payment status
                all_paid = all(
                    line.po.status == 'paid'
                    for line in po_lines
                )
                if all_paid:
                    earned += item_weight * Decimal('1.0')  # 100%
                else:
                    # PO exists but not paid = approved level
                    earned += item_weight * Decimal('0.5')  # 50%
            elif pr_status == 'approved':
                earned += item_weight * Decimal('0.5')  # 50%
            elif pr_status == 'submitted':
                earned += item_weight * Decimal('0.4')  # 40%

        return (earned, total)


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


class InventoryAllocation(models.Model):
    """
    Tracks inventory allocation for planning request items.
    Records when items are marked as taken from inventory.
    Future-proof for full stock movement tracking.
    """
    planning_request_item = models.ForeignKey(
        PlanningRequestItem,
        on_delete=models.CASCADE,
        related_name='inventory_allocations'
    )

    allocated_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text="Quantity allocated from inventory"
    )

    # Track who allocated and when
    allocated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='inventory_allocations'
    )
    allocated_at = models.DateTimeField(auto_now_add=True)

    # Future-proof: tracking fields for stock movements
    notes = models.TextField(blank=True, help_text="Optional notes about this allocation")

    class Meta:
        ordering = ['-allocated_at']
        indexes = [
            models.Index(fields=['planning_request_item', 'allocated_at']),
        ]

    def __str__(self):
        return f"Allocation: {self.allocated_quantity} of {self.planning_request_item.item.code} for {self.planning_request_item.job_no}"

    def save(self, *args, **kwargs):
        """
        When saving, update the planning request item's quantity_from_inventory.
        Also update the Item's stock_quantity.
        """
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new:
            # Update planning request item
            item = self.planning_request_item
            item.quantity_from_inventory += self.allocated_quantity
            item.quantity_to_purchase = item.quantity - item.quantity_from_inventory
            item.save(update_fields=['quantity_from_inventory', 'quantity_to_purchase'])

            # Reduce stock from Item
            catalog_item = item.item
            catalog_item.stock_quantity -= self.allocated_quantity
            catalog_item.save(update_fields=['stock_quantity'])

    def delete(self, *args, **kwargs):
        """
        When deleting, restore the quantities.
        """
        # Restore planning request item quantities
        item = self.planning_request_item
        item.quantity_from_inventory -= self.allocated_quantity
        item.quantity_to_purchase = item.quantity - item.quantity_from_inventory
        item.save(update_fields=['quantity_from_inventory', 'quantity_to_purchase'])

        # Restore stock to Item
        catalog_item = item.item
        catalog_item.stock_quantity += self.allocated_quantity
        catalog_item.save(update_fields=['stock_quantity'])

        super().delete(*args, **kwargs)
