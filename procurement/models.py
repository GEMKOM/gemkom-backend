from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator

# Create your models here.
class PaymentTerms(models.Model):
    """
    A reusable template. Example default_lines JSON structure:
    [
      {"percentage": 100.00, "label": "Advance", "basis": "immediate", "offset_days": 0},
      {"percentage": 30.00,  "label": "Advance", "basis": "immediate", "offset_days": 0},
      {"percentage": 70.00,  "label": "On Delivery", "basis": "after_delivery", "offset_days": 0},
      {"percentage": 100.00, "label": "Net 30", "basis": "after_invoice", "offset_days": 30}
    ]
    """
    BASIS_CHOICES = [
        ("immediate", "Peşin"),
        ("on_delivery", "Teslim Edildiğinde"),
        ("after_invoice", "Fatura Kesildikten Sonra"),
        ("after_delivery", "Teslimden Sonra"),
        ("custom", "Diğer"),
    ]

    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=50, unique=True)  # e.g. "advance_100", "split_30_70", "net_30"
    is_custom = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    # A list of line blueprints (see docstring). Keep it optional for fully‑custom cases.
    default_lines = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def validate_default_lines_sum(self):
        total = sum((line.get("percentage") or 0) for line in self.default_lines)
        return round(total, 2) == 100.00
    
class PaymentSchedule(models.Model):
    BASIS_CHOICES = PaymentTerms.BASIS_CHOICES

    purchase_order = models.ForeignKey(
        "PurchaseOrder", on_delete=models.CASCADE, related_name="payment_schedules"
    )
    payment_terms = models.ForeignKey(  # which template this schedule came from (optional)
        PaymentTerms, null=True, blank=True, on_delete=models.SET_NULL, related_name="schedules"
    )

    sequence = models.PositiveIntegerField(default=1)  # order of payment
    label = models.CharField(max_length=255, blank=True)  # e.g., "Advance", "On Delivery", "Net 30"
    basis = models.CharField(max_length=20, choices=BASIS_CHOICES, default="custom")
    offset_days = models.IntegerField(null=True, blank=True)

    percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="TRY")  # snapshot

    # dates & status
    due_date = models.DateField(null=True, blank=True)  # optional; fill when basis date is known
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="paid_schedules")
    paid_with_tax = models.BooleanField(default=False)

    class Meta:
        ordering = ["purchase_order", "sequence"]
        unique_together = [("purchase_order", "sequence")]

    def __str__(self):
        return f"PO-{self.purchase_order_id} · {self.percentage}% {self.label or ''}".strip()

class Supplier(models.Model):
    CURRENCY_CHOICES = [
        ('TRY', 'Türk Lirası'),
        ('USD', 'Amerikan Doları'),
        ('EUR', 'Euro'),
        ('GBP', 'İngiliz Sterlini'),
    ]
    
    # Basic Information
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')  # Fixed max_length
    default_payment_terms = models.ForeignKey(
        PaymentTerms, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="suppliers"
    )
    default_tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        default=Decimal('20.00')
    )
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name

class Item(models.Model):
    UNIT_CHOICES = [
        ('adet', 'Adet'),
        ('kg', 'KG'),
        ('metre', 'Metre'),
        ('litre', 'Litre'),
        ('paket', 'Paket'),
        ('kutu', 'Kutu'),
    ]
    code = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES)
    
    def __str__(self):
        return f"{self.code} - {self.name}"

class PurchaseRequest(models.Model):
    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('urgent', 'Acil'),
        ('critical', 'Kritik'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('submitted', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi'),
        ('cancelled', 'İptal Edildi'),
    ]
    
    # Basic Information
    request_number = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    needed_date = models.DateField(default=timezone.now)
    
    # Request Details
    requestor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purchase_requests')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Financial Information
    total_amount_eur = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency_rates_snapshot = models.JSONField(default=dict)  # Store rates at time of submission
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)     # NEW
    cancelled_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    cancellation_reason = models.TextField(blank=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.request_number} - {self.title}"
    
    def save(self, *args, **kwargs):
        if not self.request_number:
            # Auto-generate request number
            last_request = PurchaseRequest.objects.order_by('-id').first()
            if last_request:
                last_number = int(last_request.request_number.split('-')[-1])
                self.request_number = f"PR-{timezone.now().year}-{last_number + 1:04d}"
            else:
                self.request_number = f"PR-{timezone.now().year}-0001"
        super().save(*args, **kwargs)

class PurchaseRequestItem(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='request_items')
    
    # Item Details
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='requests')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)  # ADDED: Frontend sends this
    priority = models.CharField(max_length=20, choices=PurchaseRequest.PRIORITY_CHOICES, default='normal')
    specifications = models.TextField(blank=True)
    
    # Ordering
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
    
    def __str__(self):
        return f"{self.item.code} - {self.item.name}"

class PurchaseRequestItemAllocation(models.Model):
    purchase_request_item = models.ForeignKey(
        PurchaseRequestItem, on_delete=models.CASCADE, related_name="allocations"
    )
    job_no = models.CharField(max_length=20)  # keep your current length
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]
        unique_together = [("purchase_request_item", "job_no")]  # one job row per item

    def __str__(self):
        return f"{self.job_no} · {self.quantity}"

class SupplierOffer(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='offers')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='offers')
    currency = models.CharField(max_length=3, choices=Supplier.CURRENCY_CHOICES, default='TRY')
    payment_terms = models.ForeignKey(PaymentTerms, on_delete=models.CASCADE, related_name="supplier_offers", null=True, blank=True)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        default=Decimal('20.00')
    )
    notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['purchase_request', 'supplier']
    
    def __str__(self):
        return f"{self.supplier.name} - {self.purchase_request.request_number}"
    
class ItemOffer(models.Model):
    purchase_request_item = models.ForeignKey(PurchaseRequestItem, on_delete=models.CASCADE, related_name='offers')
    supplier_offer = models.ForeignKey(SupplierOffer, on_delete=models.CASCADE, related_name='item_offers')
    
    # Offer Details
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    total_price = models.DecimalField(max_digits=15, decimal_places=2)
    delivery_days = models.PositiveIntegerField(null=True, blank=True)  # CORRECTED: Item-level delivery days
    notes = models.TextField(blank=True)
    
    # Recommendation - CORRECTED: Frontend tracks recommendations at item level
    is_recommended = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['purchase_request_item', 'supplier_offer']
    
    def __str__(self):
        return f"{self.purchase_request_item.item.name} - {self.supplier_offer.supplier.name}"

class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ("awaiting_payment", "Ödeme Bekliyor"),                          # after invoice arrives / operations start
        ("paid", "Ödendi"),
        ("cancelled", "Cancelled"),
    ]

    pr = models.ForeignKey('PurchaseRequest', on_delete=models.PROTECT, related_name='purchase_orders')
    supplier_offer = models.ForeignKey('SupplierOffer', on_delete=models.PROTECT, related_name='purchase_orders')
    supplier = models.ForeignKey('Supplier', on_delete=models.PROTECT, related_name='purchase_orders')

    currency = models.CharField(max_length=3, default='TRY')  # for now: supplier.default_currency
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        default=Decimal('20.00')
    )
    # Persisted tax total for audit/reporting. (Gross = computed on frontend.)
    total_tax_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='awaiting_payment')
    priority = models.CharField(max_length=20, default='normal')  # mirror PR

    created_at = models.DateTimeField(auto_now_add=True)
    ordered_at = models.DateTimeField(null=True, blank=True)  # fill later if needed

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"PO-{self.id} | {self.supplier.name}"

    def recompute_totals(self):
        """
        Recompute net total from lines, then recompute tax from immutable po.tax_rate.
        """
        from decimal import Decimal, ROUND_HALF_UP

        def Q2(x: Decimal) -> Decimal:
            return Decimal(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        net = sum((l.total_price or Decimal('0')) for l in self.lines.all())
        rate = (self.tax_rate or Decimal('0')) / Decimal('100')
        tax = Q2(Decimal(net) * rate)

        updates = {}
        if net != self.total_amount:
            updates['total_amount'] = net
        if tax != self.total_tax_amount:
            updates['total_tax_amount'] = tax

        if updates:
            for k, v in updates.items():
                setattr(self, k, v)
            self.save(update_fields=list(updates.keys()))


class PurchaseOrderLine(models.Model):
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')

    # Source of truth = the ItemOffer we awarded (recommended)
    item_offer = models.ForeignKey('ItemOffer', on_delete=models.PROTECT, related_name='po_lines')
    purchase_request_item = models.ForeignKey('PurchaseRequestItem', on_delete=models.PROTECT, related_name='+')

    # Freeze values at PO creation time
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    total_price = models.DecimalField(max_digits=16, decimal_places=2)
    delivery_days = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['id']

    def validate_allocation_totals(self):
        from django.db.models import Sum
        sums = self.allocations.aggregate(
            q=Sum('quantity'),
            a=Sum('amount')
        )
        q_sum = sums['q'] or Decimal('0')
        a_sum = (sums['a'] or Decimal('0')).quantize(Decimal('0.01'))
        if q_sum != self.quantity or a_sum != self.total_price.quantize(Decimal('0.01')):
            raise ValueError("Allocations must sum to line quantity and total price.")
        
class PurchaseOrderLineAllocation(models.Model):
    """
    Splits a PO line across one or more job numbers.
    Keep amounts derived from quantity*unit_price for fast reporting.
    """
    po_line = models.ForeignKey(
        'PurchaseOrderLine',
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    job_no = models.CharField(max_length=50)  # keep same style as PRItem.job_no
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    amount = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['job_no']),
        ]

    def __str__(self):
        return f"{self.po_line_id} · {self.job_no} · {self.quantity}"