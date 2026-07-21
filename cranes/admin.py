from django.contrib import admin

from .models import CraneRate, CraneRequest, CraneType


@admin.register(CraneType)
class CraneTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'sort_order')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    ordering = ('sort_order',)


@admin.register(CraneRate)
class CraneRateAdmin(admin.ModelAdmin):
    list_display = (
        'crane_type', 'effective_from', 'currency',
        'price_up_to_3h', 'price_up_to_8h', 'price_per_day',
        'transport_fee', 'rigger_fee',
    )
    list_filter = ('crane_type__category', 'currency')
    search_fields = ('crane_type__name',)
    ordering = ('crane_type__sort_order', '-effective_from')


@admin.register(CraneRequest)
class CraneRequestAdmin(admin.ModelAdmin):
    list_display = (
        'request_number', 'department', 'job_no', 'crane_type',
        'pricing_option', 'status', 'estimated_cost', 'actual_cost',
        'requestor', 'needed_date', 'created_at',
    )
    list_filter = ('status', 'department', 'priority', 'crane_type__category')
    search_fields = ('request_number', 'job_no', 'requestor__username', 'crane_type__name')
    readonly_fields = ('request_number', 'created_at', 'submitted_at', 'estimate_breakdown')
    ordering = ('-created_at',)
