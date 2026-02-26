from django.contrib import admin

from .models import (
    OfferTemplate,
    OfferTemplateNode,
    SalesOffer,
    SalesOfferItem,
    SalesOfferFile,
    SalesOfferPriceRevision,
)


# =============================================================================
# Offer Template
# =============================================================================

class OfferTemplateNodeInline(admin.TabularInline):
    model = OfferTemplateNode
    extra = 0
    fields = ['title', 'parent', 'sequence', 'is_active', 'description']
    ordering = ['sequence']


@admin.register(OfferTemplate)
class OfferTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_by', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'description']
    inlines = [OfferTemplateNodeInline]
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OfferTemplateNode)
class OfferTemplateNodeAdmin(admin.ModelAdmin):
    list_display = ['title', 'template', 'parent', 'sequence', 'is_active']
    list_filter = ['template', 'is_active']
    search_fields = ['title', 'description']
    ordering = ['template', 'sequence']


# =============================================================================
# Sales Offer
# =============================================================================

class SalesOfferItemInline(admin.TabularInline):
    model = SalesOfferItem
    extra = 0
    fields = ['template_node', 'title_override', 'quantity', 'sequence', 'notes']
    ordering = ['sequence']


class SalesOfferFileInline(admin.TabularInline):
    model = SalesOfferFile
    extra = 0
    fields = ['file', 'file_type', 'name', 'uploaded_by', 'uploaded_at']
    readonly_fields = ['uploaded_at']


class SalesOfferPriceRevisionInline(admin.TabularInline):
    model = SalesOfferPriceRevision
    extra = 0
    fields = ['revision_type', 'amount', 'currency', 'approval_round', 'is_current', 'created_by', 'created_at']
    readonly_fields = ['created_at']
    ordering = ['created_at']


@admin.register(SalesOffer)
class SalesOfferAdmin(admin.ModelAdmin):
    list_display = [
        'offer_no', 'title', 'customer', 'status',
        'approval_round', 'created_by', 'created_at',
    ]
    list_filter = ['status', 'customer']
    search_fields = ['offer_no', 'title', 'customer__name', 'customer__code']
    ordering = ['-created_at']
    readonly_fields = [
        'offer_no', 'approval_round',
        'submitted_to_customer_at', 'won_at', 'lost_at', 'cancelled_at',
        'created_at', 'updated_at',
    ]
    inlines = [SalesOfferItemInline, SalesOfferFileInline, SalesOfferPriceRevisionInline]
    fieldsets = [
        (None, {
            'fields': ['offer_no', 'customer', 'title', 'description',
                       'customer_inquiry_ref', 'delivery_date_requested'],
        }),
        ('Durum', {
            'fields': ['status', 'approval_round', 'converted_job_order'],
        }),
        ('Zaman Damgaları', {
            'fields': ['submitted_to_customer_at', 'won_at', 'lost_at', 'cancelled_at',
                       'created_by', 'created_at', 'updated_at'],
            'classes': ['collapse'],
        }),
    ]


@admin.register(SalesOfferPriceRevision)
class SalesOfferPriceRevisionAdmin(admin.ModelAdmin):
    list_display = ['offer', 'revision_type', 'amount', 'currency', 'approval_round', 'is_current', 'created_at']
    list_filter = ['revision_type', 'currency', 'is_current']
    search_fields = ['offer__offer_no']
    ordering = ['offer', 'created_at']
    readonly_fields = ['created_at']
