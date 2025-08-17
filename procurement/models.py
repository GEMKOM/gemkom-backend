from django.db import transaction
from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class PaymentType(models.Model):
    name = models.CharField()

class Provider(models.Model):
    CURRENCY_TYPES = [
        ('USD', '$'),
        ('EUR', '€'),
        ('TRY', '₺')
    ]
    name = models.CharField()
    default_payment_method = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name="providers")
    default_currency = models.CharField(max_length=10, choices=CURRENCY_TYPES)

class Item(models.Model):
    stock_code = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=100)

class PurchaseRequest(models.Model):
    request_no = models.CharField(max_length=50, unique=True)
    job_no = models.CharField(max_length=100)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="purchase_requests")
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Taslak'),
        ('pending', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi')
    ], default='draft')

    def save(self, *args, **kwargs):
        if not self.request_no:
            with transaction.atomic():
                last = PurchaseRequest.objects.select_for_update().order_by('-id').first()
                next_id = 1 if not last else last.id + 1
                self.request_no = f"PR-{next_id:05d}"
        super().save(*args, **kwargs)

class ProviderOffer(models.Model):
    CURRENCY_TYPES = [
        ('USD', '$'),
        ('EUR', '€'),
        ('TRY', '₺'),
        ('GBP', '£')
    ]
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="offers")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="offers")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, choices=CURRENCY_TYPES)
    payment_type = models.ForeignKey(PaymentType, on_delete=models.CASCADE)

class ItemSelection(models.Model):
    item = models.OneToOneField(Item, on_delete=models.CASCADE, related_name="selection")
    offer = models.ForeignKey(ProviderOffer, on_delete=models.CASCADE)
    selected_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    selected_at = models.DateTimeField(auto_now_add=True)

class ApprovalStep(models.Model):
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Onay Bekliyor'),
        ('approved', 'Onaylandı'),
        ('rejected', 'Reddedildi')
    ], default='pending')
    comment = models.TextField(null=True, blank=True)
    decision_date = models.DateTimeField(null=True, blank=True)
