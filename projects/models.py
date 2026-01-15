from django.db import models
from django.contrib.auth.models import User


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
    short_name = models.CharField(max_length=50, blank=True)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    # Tax and billing
    tax_id = models.CharField(max_length=50, blank=True)
    tax_office = models.CharField(max_length=100, blank=True)

    # Preferred terms
    default_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        default='TRY'
    )

    # Status
    is_active = models.BooleanField(default=True)

    # Notes
    notes = models.TextField(blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customers_created'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
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
