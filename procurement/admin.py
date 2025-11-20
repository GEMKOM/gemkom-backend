from django.contrib import admin

from procurement.models import PurchaseOrder, PurchaseOrderLine, Item, PurchaseRequest

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


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ('request_number', 'title', 'status', 'priority', 'requestor', 'created_at')
    list_filter = ('status', 'priority', 'created_at')
    search_fields = ('request_number', 'title', 'description')
    readonly_fields = ('request_number', 'created_at', 'updated_at', 'submitted_at', 'display_planning_requests')
    filter_horizontal = ('planning_requests',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('request_number', 'title', 'description', 'needed_date', 'priority')
        }),
        ('Request Details', {
            'fields': ('requestor', 'status', 'total_amount_eur')
        }),
        ('Planning Requests', {
            'fields': ('planning_requests', 'display_planning_requests'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'submitted_at'),
            'classes': ('collapse',)
        }),
    )

    def display_planning_requests(self, obj):
        """Display linked planning requests"""
        if obj.pk:
            prs = obj.planning_requests.all()
            if prs.exists():
                return ', '.join([f'{pr.request_number}' for pr in prs])
            return 'None'
        return '-'
    display_planning_requests.short_description = 'Planning Requests (Read-only)'


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'unit')
    search_fields = ('code', 'name')  # Required for autocomplete
    list_filter = ('unit',)
    ordering = ('code',)