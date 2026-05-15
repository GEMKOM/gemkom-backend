from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

User = settings.AUTH_USER_MODEL

CURRENCY_CHOICES = [
    ("TRY", "TRY"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("GBP", "GBP"),
]


# ---------------------------------------------------------------------------
# 1. Monthly Expense
# ---------------------------------------------------------------------------

class MonthlyExpense(models.Model):
    CATEGORY_CHOICES = [
        ("catering",   "Yemekhane / Catering"),
        ("security",   "Güvenlik"),
        ("transport",  "Servis / Ulaşım"),
        ("rent",       "Kira"),
        ("utilities",  "Elektrik / Su / Doğalgaz"),
        ("insurance",  "Sigorta"),
        ("other",      "Diğer"),
    ]
    RECURRENCE_CHOICES = [
        ("once",      "Tek Sefer"),
        ("monthly",   "Aylık"),
        ("quarterly", "3 Aylık"),
        ("annual",    "Yıllık"),
    ]
    STATUS_CHOICES = [
        ("active",    "Aktif"),
        ("cancelled", "İptal Edildi"),
    ]

    category    = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.CharField(max_length=255)
    amount      = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency    = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")
    recurrence  = models.CharField(max_length=20, choices=RECURRENCE_CHOICES, default="monthly")
    start_date  = models.DateField()
    end_date    = models.DateField(null=True, blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes       = models.TextField(blank=True)

    created_by  = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_category_display()} — {self.description} ({self.amount} {self.currency})"


# ---------------------------------------------------------------------------
# 2. Loan + LoanInstallment
# ---------------------------------------------------------------------------

class Loan(models.Model):
    STATUS_CHOICES = [
        ("active",    "Aktif"),
        ("paid_off",  "Kapatıldı"),
        ("cancelled", "İptal Edildi"),
    ]

    name               = models.CharField(max_length=255)
    principal          = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    interest_rate      = models.DecimalField(max_digits=7, decimal_places=4, validators=[MinValueValidator(Decimal("0"))])  # annual %
    term_months        = models.PositiveIntegerField()
    currency           = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")
    first_payment_date = models.DateField()
    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes              = models.TextField(blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.principal} {self.currency})"

    def generate_installments(self):
        """
        (Re)generate amortization schedule. Deletes existing installments first.
        Formula: M = P * r(1+r)^n / ((1+r)^n - 1)
        where r = annual_rate / 12 / 100
        """
        from dateutil.relativedelta import relativedelta

        self.installments.all().delete()

        P = Decimal(str(self.principal))
        annual_rate = Decimal(str(self.interest_rate))
        n = self.term_months

        if annual_rate == 0:
            monthly_payment = (P / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            r = Decimal("0")
        else:
            r = annual_rate / Decimal("1200")  # monthly rate
            factor = (1 + r) ** n
            monthly_payment = (P * r * factor / (factor - 1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        balance = P
        installments = []
        for i in range(1, n + 1):
            interest = (balance * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            principal_component = monthly_payment - interest
            if i == n:
                # Final installment absorbs rounding residual
                principal_component = balance
                monthly_payment = principal_component + interest
            balance -= principal_component

            from dateutil.relativedelta import relativedelta
            due = self.first_payment_date + relativedelta(months=i - 1)

            installments.append(LoanInstallment(
                loan=self,
                sequence=i,
                due_date=due,
                principal_component=principal_component,
                interest_component=interest,
                total_payment=principal_component + interest,
            ))

        LoanInstallment.objects.bulk_create(installments)


class LoanInstallment(models.Model):
    loan                = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="installments")
    sequence            = models.PositiveIntegerField()
    due_date            = models.DateField(db_index=True)
    principal_component = models.DecimalField(max_digits=16, decimal_places=2)
    interest_component  = models.DecimalField(max_digits=16, decimal_places=2)
    total_payment       = models.DecimalField(max_digits=16, decimal_places=2)
    is_paid             = models.BooleanField(default=False)
    paid_at             = models.DateTimeField(null=True, blank=True)
    paid_by             = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["loan", "sequence"]
        unique_together = [("loan", "sequence")]

    def __str__(self):
        return f"{self.loan.name} — installment {self.sequence} due {self.due_date}"


# ---------------------------------------------------------------------------
# 3. Tax Entry
# ---------------------------------------------------------------------------

class TaxEntry(models.Model):
    TAX_TYPE_CHOICES = [
        ("vat",                   "KDV"),
        ("corporate_tax",         "Kurumlar Vergisi"),
        ("sgk",                   "SGK"),
        ("income_tax_withholding","Gelir Vergisi Stopajı"),
        ("other",                 "Diğer"),
    ]

    tax_type     = models.CharField(max_length=30, choices=TAX_TYPE_CHOICES)
    period_label = models.CharField(max_length=100, blank=True)  # e.g. "Nisan 2026 KDV"
    description  = models.CharField(max_length=255, blank=True)
    amount       = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency     = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")
    due_date     = models.DateField(db_index=True)
    is_paid      = models.BooleanField(default=False)
    paid_at      = models.DateTimeField(null=True, blank=True)
    paid_by      = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notes        = models.TextField(blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="tax_entries_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date"]
        verbose_name_plural = "Tax entries"

    def __str__(self):
        return f"{self.get_tax_type_display()} — {self.period_label or self.due_date} ({self.amount} {self.currency})"


# ---------------------------------------------------------------------------
# 4. Expected Receipt + Installment
# ---------------------------------------------------------------------------

class ExpectedReceipt(models.Model):
    STATUS_CHOICES = [
        ("expected",  "Bekleniyor"),
        ("received",  "Tahsil Edildi"),
        ("cancelled", "İptal Edildi"),
    ]

    title        = models.CharField(max_length=255)
    description  = models.TextField(blank=True)
    reference_no = models.CharField(max_length=100, blank=True)
    customer_name= models.CharField(max_length=200)
    job_order    = models.ForeignKey(
        "projects.JobOrder", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="expected_receipts",
    )
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency     = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="EUR")
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default="expected")
    notes        = models.TextField(blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.customer_name} ({self.total_amount} {self.currency})"


class ExpectedReceiptInstallment(models.Model):
    receipt     = models.ForeignKey(ExpectedReceipt, on_delete=models.CASCADE, related_name="installments")
    sequence    = models.PositiveIntegerField()
    label       = models.CharField(max_length=100, blank=True)  # e.g. "Avans", "Milestone 1", "Bakiye"
    amount      = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency    = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    due_date    = models.DateField(null=True, blank=True, db_index=True)
    is_received = models.BooleanField(default=False)
    received_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    notes       = models.TextField(blank=True)

    class Meta:
        ordering = ["receipt", "sequence"]
        unique_together = [("receipt", "sequence")]

    def __str__(self):
        return f"{self.receipt.title} — installment {self.sequence}"


# ---------------------------------------------------------------------------
# 5. Ad-hoc Job Cost
# ---------------------------------------------------------------------------

class AdHocJobCost(models.Model):
    CATEGORY_CHOICES = [
        ("material",  "Malzeme"),
        ("service",   "Hizmet"),
        ("transport", "Nakliye"),
        ("other",     "Diğer"),
    ]

    job_order   = models.ForeignKey(
        "projects.JobOrder", on_delete=models.PROTECT, related_name="adhoc_costs",
    )
    description = models.CharField(max_length=255)
    amount      = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency    = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="TRY")
    cost_date   = models.DateField(db_index=True)
    category    = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other")
    notes       = models.TextField(blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cost_date"]

    def __str__(self):
        return f"{self.job_order_id} — {self.description} ({self.amount} {self.currency})"
