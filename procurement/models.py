from django.db import transaction
from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class PaymentType(models.Model):
    name = models.CharField()

class Provider(models.Model):
    name = models.CharField()
    default_payment_method = models.ForeignKey(PaymentType, on_delete=models.CASCADE, related_name="providers")

class PurchaseRequest(models.Model):
    request_no = models.CharField(max_length=50, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='draft')

    def save(self, *args, **kwargs):
        if not self.request_no:
            with transaction.atomic():
                last = PurchaseRequest.objects.select_for_update().order_by('-id').first()
                next_id = 1 if not last else last.id + 1
                self.request_no = f"PR-{next_id:05d}"
        super().save(*args, **kwargs)

class Item(models.Model):
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="items")
    name = models.CharField(max_length=255)
    job_no = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

class ProviderOffer(models.Model):
    CURRENCY_TYPES = [
        ('USD', '$'),
        ('EUR', '€'),
        ('TRY', '₺')
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
