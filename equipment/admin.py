from django.contrib import admin

from .models import EquipmentItem, EquipmentCheckout


class EquipmentCheckoutInline(admin.TabularInline):
    model = EquipmentCheckout
    extra = 0
    fields = ('quantity', 'checked_out_by', 'checked_out_at', 'job_order', 'purpose', 'checked_in_at', 'checked_in_by')
    readonly_fields = ('checked_out_at',)
    can_delete = False


@admin.register(EquipmentItem)
class EquipmentItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'asset_type', 'category', 'quantity', 'location', 'is_active', 'created_at')
    list_filter = ('asset_type', 'category', 'is_active')
    search_fields = ('code', 'name', 'description')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [EquipmentCheckoutInline]


@admin.register(EquipmentCheckout)
class EquipmentCheckoutAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'quantity', 'checked_out_by', 'checked_out_at', 'job_order', 'is_returned_display', 'checked_in_at')
    list_filter = ('item__asset_type', 'item__category')
    search_fields = ('item__code', 'item__name', 'checked_out_by__username', 'job_order__job_no')
    readonly_fields = ('checked_out_at', 'created_at', 'updated_at')

    @admin.display(boolean=True, description='Returned')
    def is_returned_display(self, obj):
        return obj.is_returned
