import os
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.storages import PrivateMediaStorage
from projects.models import Customer, JobOrder, CURRENCY_CHOICES


# =============================================================================
# Product Catalog
# =============================================================================

class OfferTemplate(models.Model):
    """
    Product family / catalog container.
    Groups related products that the company manufactures.
    Examples: "MELTSHOP EQUIPMENT", "PELLETIZING PLANT", "AUXILIARY SYSTEMS"
    """
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='offer_templates_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Teklif Şablonu'
        verbose_name_plural = 'Teklif Şablonları'

    def __str__(self):
        return self.name


class OfferTemplateNode(models.Model):
    """
    Individual product/component in the catalog.
    Forms a tree via self-FK — represents items the company can manufacture.

    NOTE: Department tasks are NOT created from this template.
    They are added manually to job orders after offer conversion via
    the existing apply_template endpoint.
    """
    template = models.ForeignKey(
        OfferTemplate,
        on_delete=models.CASCADE,
        related_name='nodes'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    sequence = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['template', 'sequence']
        verbose_name = 'Katalog Öğesi'
        verbose_name_plural = 'Katalog Öğeleri'

    def __str__(self):
        if self.parent:
            return f"{self.template.name} / {self.parent.title} / {self.title}"
        return f"{self.template.name} / {self.title}"

    def get_depth(self):
        depth = 0
        node = self
        while node.parent_id:
            depth += 1
            node = node.parent
        return depth


# =============================================================================
# Sales Offer
# =============================================================================

class SalesOffer(models.Model):
    """
    A sales offer / project quote tracked before becoming a job order.
    Workflow: draft → consultation → pricing → pending_approval → approved
              → submitted_customer → won/lost/cancelled
    """
    STATUS_CHOICES = [
        ('draft',              'Taslak'),
        ('consultation',       'Danışma'),
        ('pricing',            'Fiyatlandırma'),
        ('pending_approval',   'Onay Bekliyor'),
        ('approved',           'Onaylandı'),
        ('submitted_customer', 'Müşteriye Sunuldu'),
        ('won',                'Kazanıldı'),
        ('lost',               'Kaybedildi'),
        ('cancelled',          'İptal Edildi'),
    ]

    # Auto-generated: OF-{year}-{seq:04d}
    offer_no = models.CharField(max_length=20, unique=True, db_index=True)

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='sales_offers'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    customer_inquiry_ref = models.CharField(
        max_length=100,
        blank=True,
        help_text="Customer's own PO or reference number"
    )
    delivery_date_requested = models.DateField(null=True, blank=True)
    offer_expiry_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )

    # Set when offer is won and converted to job orders
    converted_job_order = models.ForeignKey(
        JobOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='primary_offer'
    )

    # Increments on each submit-for-approval call (tracks revision cycles)
    approval_round = models.PositiveIntegerField(default=0)

    # Timestamps
    submitted_to_customer_at = models.DateTimeField(null=True, blank=True)
    won_at = models.DateTimeField(null=True, blank=True)
    lost_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_offers_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'customer']),
        ]
        verbose_name = 'Satış Teklifi'
        verbose_name_plural = 'Satış Teklifleri'

    def __str__(self):
        return f"{self.offer_no} – {self.title}"

    # -------------------------------------------------------------------------
    # Approval event hook (called by approvals.services._notify_subject)
    # -------------------------------------------------------------------------
    def handle_approval_event(self, workflow, event, payload):
        if event == 'approved':
            self.status = 'approved'
            self.save(update_fields=['status', 'updated_at'])

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------
    @property
    def current_price(self):
        return self.price_revisions.filter(is_current=True).first()

    @property
    def total_price(self):
        from decimal import Decimal
        total = Decimal('0.00')
        for item in self.items.all():
            if item.unit_price is not None:
                total += item.unit_price * item.quantity
        return total

    @property
    def total_weight_kg(self):
        from decimal import Decimal
        total = Decimal('0.00')
        for item in self.items.all():
            if item.weight_kg is not None:
                total += item.weight_kg * item.quantity
        return total

    @property
    def has_catalog_items(self):
        return self.items.filter(template_node__isnull=False).exists()


class SalesOfferItem(models.Model):
    """
    One line item in the offer — a product selected from the catalog,
    or a custom item if no catalog match.

    Each item with a template_node becomes a job order (or a child job order
    if its nearest selected ancestor is also in the offer) on conversion.
    Custom items (template_node=None) always become root job orders.
    """
    offer = models.ForeignKey(
        SalesOffer,
        on_delete=models.CASCADE,
        related_name='items'
    )
    template_node = models.ForeignKey(
        OfferTemplateNode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='offer_items'
    )
    quantity = models.PositiveIntegerField(default=1)
    title_override = models.CharField(
        max_length=255,
        blank=True,
        help_text='Overrides template_node.title for the created job order title'
    )
    notes = models.TextField(blank=True)
    sequence = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='offer_items_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['offer', 'sequence']
        verbose_name = 'Teklif Kalemi'
        verbose_name_plural = 'Teklif Kalemleri'

    def __str__(self):
        title = self.title_override or (self.template_node.title if self.template_node else '—')
        return f"{self.offer.offer_no} – {title} × {self.quantity}"

    def clean(self):
        if not self.template_node_id and not self.title_override:
            raise ValidationError(
                "Either template_node or title_override must be provided."
            )

    @property
    def resolved_title(self):
        if self.title_override:
            return self.title_override
        if self.template_node:
            return self.template_node.title
        return ''

    @property
    def subtotal(self):
        if self.unit_price is not None:
            return self.unit_price * self.quantity
        return None


# =============================================================================
# Offer Files
# =============================================================================

def sales_offer_file_upload_path(instance, filename):
    return os.path.join('sales_offer_files', instance.offer.offer_no, filename)


class SalesOfferFile(models.Model):
    """File attachment for a sales offer. Follows projects.JobOrderFile pattern."""

    FILE_TYPE_CHOICES = [
        ('drawing',       'Çizim'),
        ('specification', 'Şartname'),
        ('quotation',     'Fiyat Teklifi'),
        ('correspondence','Yazışma'),
        ('photo',         'Fotoğraf'),
        ('other',         'Diğer'),
    ]

    offer = models.ForeignKey(
        SalesOffer,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(
        upload_to=sales_offer_file_upload_path,
        storage=PrivateMediaStorage()
    )
    file_type = models.CharField(
        max_length=20,
        choices=FILE_TYPE_CHOICES,
        default='other'
    )
    name = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales_offer_files_uploaded'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'Teklif Dosyası'
        verbose_name_plural = 'Teklif Dosyaları'

    def __str__(self):
        return f"{self.offer.offer_no} – {self.name or self.filename}"

    def save(self, *args, **kwargs):
        if not self.name and self.file:
            self.name = os.path.basename(self.file.name)
        super().save(*args, **kwargs)

    @property
    def filename(self):
        return os.path.basename(self.file.name) if self.file else ''

    @property
    def file_size(self):
        try:
            return self.file.size
        except Exception:
            return None


# =============================================================================
# Price Revisions
# =============================================================================

class SalesOfferPriceRevision(models.Model):
    """
    Tracks all price proposals across all approval rounds.
    Exactly one record per offer has is_current=True at any time.
    """
    REVISION_TYPE_CHOICES = [
        ('initial',          'İlk Teklif'),
        ('sales_revision',   'Satış Revizyonu'),
        ('approver_counter', 'Onaylayıcı Karşı Teklifi'),
        ('approved',         'Onaylanan Fiyat'),
    ]

    offer = models.ForeignKey(
        SalesOffer,
        on_delete=models.CASCADE,
        related_name='price_revisions'
    )
    revision_type = models.CharField(max_length=20, choices=REVISION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='EUR')

    # Which approval round this belongs to
    approval_round = models.PositiveIntegerField(default=1)

    # Approver's counter-price when rejecting (informational, is_current stays False)
    counter_amount = models.DecimalField(
        max_digits=16, decimal_places=2, null=True, blank=True
    )
    counter_currency = models.CharField(
        max_length=3, choices=CURRENCY_CHOICES, blank=True
    )

    notes = models.TextField(blank=True)
    is_current = models.BooleanField(default=False, db_index=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='price_revisions_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['offer', 'created_at']
        indexes = [
            models.Index(fields=['offer', 'is_current']),
            models.Index(fields=['offer', 'approval_round']),
        ]
        verbose_name = 'Fiyat Revizyonu'
        verbose_name_plural = 'Fiyat Revizyonları'

    def __str__(self):
        return (
            f"{self.offer.offer_no} – {self.get_revision_type_display()} "
            f"{self.amount} {self.currency}"
        )

    def save(self, *args, **kwargs):
        # Ensure only one is_current per offer at a time
        if self.is_current and not self.pk:
            SalesOfferPriceRevision.objects.filter(
                offer=self.offer, is_current=True
            ).update(is_current=False)
        super().save(*args, **kwargs)
