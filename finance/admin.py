from django.contrib import admin

from .models import (
    MonthlyExpense,
    Loan, LoanInstallment,
    TaxEntry,
    ExpectedReceipt, ExpectedReceiptInstallment,
    SalesOfferInstallmentReceipt,
    AdHocJobCost,
)


# ---------------------------------------------------------------------------
# MonthlyExpense
# ---------------------------------------------------------------------------

@admin.register(MonthlyExpense)
class MonthlyExpenseAdmin(admin.ModelAdmin):
    list_display  = ('description', 'category', 'amount', 'currency', 'recurrence', 'start_date', 'status')
    list_filter   = ('category', 'recurrence', 'status', 'currency')
    search_fields = ('description', 'notes')
    ordering      = ('-created_at',)
    readonly_fields = ('created_by', 'created_at', 'updated_at')


# ---------------------------------------------------------------------------
# Loan + LoanInstallment
# ---------------------------------------------------------------------------

class LoanInstallmentInline(admin.TabularInline):
    model        = LoanInstallment
    extra        = 0
    readonly_fields = ('sequence', 'due_date', 'principal_component', 'interest_component', 'total_payment', 'is_paid', 'paid_at', 'paid_by')
    can_delete   = False
    show_change_link = False


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display  = ('name', 'principal', 'currency', 'interest_rate', 'term_months', 'first_payment_date', 'status')
    list_filter   = ('status', 'currency')
    search_fields = ('name', 'notes')
    ordering      = ('-created_at',)
    readonly_fields = ('created_by', 'created_at')
    inlines       = [LoanInstallmentInline]


# ---------------------------------------------------------------------------
# TaxEntry
# ---------------------------------------------------------------------------

@admin.register(TaxEntry)
class TaxEntryAdmin(admin.ModelAdmin):
    list_display  = ('tax_type', 'period_label', 'amount', 'currency', 'due_date', 'is_paid', 'paid_at')
    list_filter   = ('tax_type', 'is_paid', 'currency')
    search_fields = ('period_label', 'description', 'notes')
    ordering      = ('due_date',)
    readonly_fields = ('created_by', 'created_at', 'paid_by', 'paid_at')
    date_hierarchy = 'due_date'


# ---------------------------------------------------------------------------
# ExpectedReceipt + Installments
# ---------------------------------------------------------------------------

class ExpectedReceiptInstallmentInline(admin.TabularInline):
    model        = ExpectedReceiptInstallment
    extra        = 0
    readonly_fields = ('received_at', 'received_by')
    fields        = ('sequence', 'label', 'amount', 'currency', 'due_date', 'is_received', 'received_at', 'received_by', 'notes')


@admin.register(ExpectedReceipt)
class ExpectedReceiptAdmin(admin.ModelAdmin):
    list_display  = ('title', 'customer_name', 'job_order', 'total_amount', 'currency', 'status', 'created_at')
    list_filter   = ('status', 'currency')
    search_fields = ('title', 'customer_name', 'reference_no')
    ordering      = ('-created_at',)
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    raw_id_fields = ('job_order',)
    inlines       = [ExpectedReceiptInstallmentInline]


# ---------------------------------------------------------------------------
# SalesOfferInstallmentReceipt
# ---------------------------------------------------------------------------

@admin.register(SalesOfferInstallmentReceipt)
class SalesOfferInstallmentReceiptAdmin(admin.ModelAdmin):
    list_display  = ('offer', 'sequence', 'is_received', 'received_at', 'received_by')
    list_filter   = ('is_received',)
    search_fields = ('offer__offer_no',)
    ordering      = ('offer', 'sequence')
    readonly_fields = ('received_at', 'received_by')
    raw_id_fields = ('offer',)


# ---------------------------------------------------------------------------
# AdHocJobCost
# ---------------------------------------------------------------------------

@admin.register(AdHocJobCost)
class AdHocJobCostAdmin(admin.ModelAdmin):
    list_display  = ('job_order', 'description', 'category', 'amount', 'currency', 'cost_date', 'created_by')
    list_filter   = ('category', 'currency')
    search_fields = ('job_order__job_no', 'description', 'notes')
    ordering      = ('-cost_date',)
    readonly_fields = ('created_by', 'created_at', 'updated_at')
    raw_id_fields = ('job_order',)
    date_hierarchy = 'cost_date'
