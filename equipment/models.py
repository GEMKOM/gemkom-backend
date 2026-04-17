from django.conf import settings
from django.db import models
from django.db.models import Sum, Q


class EquipmentItem(models.Model):
    ASSET_TYPE_CHOICES = [
        ('hand_tool', 'Hand Tool'),
        ('power_tool', 'Power Tool'),
        ('instrument', 'Instrument'),
        ('consumable', 'Consumable'),
        ('other', 'Other'),
    ]

    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPE_CHOICES, default='other')
    category = models.CharField(max_length=100, null=True, blank=True, db_index=True)
    quantity = models.PositiveIntegerField(default=1)
    location = models.CharField(max_length=255, blank=True, default='Ambar')
    is_active = models.BooleanField(default=True)
    properties = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['asset_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def checked_out_quantity(self):
        result = self.checkouts.filter(
            checked_in_at__isnull=True
        ).aggregate(total=Sum('quantity'))
        return result['total'] or 0

    @property
    def available_quantity(self):
        return self.quantity - self.checked_out_quantity


class EquipmentCheckout(models.Model):
    item = models.ForeignKey(
        EquipmentItem,
        on_delete=models.PROTECT,
        related_name='checkouts',
    )
    quantity = models.PositiveIntegerField(default=1)
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='equipment_checkouts',
    )
    checked_out_at = models.DateTimeField(auto_now_add=True)
    job_order = models.ForeignKey(
        'projects.JobOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_checkouts',
        to_field='job_no',
    )
    purpose = models.CharField(max_length=255, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='equipment_checkins',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-checked_out_at']
        indexes = [
            models.Index(fields=['item', 'checked_in_at']),
            models.Index(fields=['checked_out_by', 'checked_in_at']),
        ]

    def __str__(self):
        status = 'returned' if self.checked_in_at else 'out'
        return f"Checkout #{self.pk} | {self.item.code} x{self.quantity} | {status}"

    @property
    def is_returned(self):
        return self.checked_in_at is not None
