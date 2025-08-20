from django.contrib import admin

from procurement.models import PurchaseOrder, PurchaseOrderLine

# Register your models here.
class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    readonly_fields = ('item_offer','purchase_request_item','quantity','unit_price','total_price')

@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('id','supplier','pr','currency','total_amount','status','priority','created_at')
    list_filter = ('status','currency','priority','supplier')
    inlines = [PurchaseOrderLineInline]