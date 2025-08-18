from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

# Create your models here.
class PaymentType(models.Model):
    name = models.CharField(max_length=100)  # Added max_length
    
    def __str__(self):
        return self.name

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
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')
    default_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TRY')  # Fixed max_length
    default_payment_method = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name="suppliers", null=True, blank=True)  # Fixed related_name
    
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
        ('rejected', 'Reddedildi')
    ]
    
    # Basic Information
    request_number = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
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
    job_no = models.CharField(max_length=20, blank=True, null=True)
    specifications = models.TextField(blank=True)
    
    # Ordering
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['order']
    
    def __str__(self):
        return f"{self.item.code} - {self.item.name}"

class SupplierOffer(models.Model):
    purchase_request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='offers')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='offers')
    payment_method = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name="supplier_offers", null=True, blank=True)
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
