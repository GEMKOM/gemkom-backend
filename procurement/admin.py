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
    readonly_fields = ('request_number', 'created_at', 'updated_at', 'submitted_at', 'display_planning_request_items', 'display_planning_requests')
    filter_horizontal = ('planning_request_items',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('request_number', 'title', 'description', 'needed_date', 'priority')
        }),
        ('Request Details', {
            'fields': ('requestor', 'status', 'total_amount_eur')
        }),
        ('Planning Request Items', {
            'fields': ('planning_request_items', 'display_planning_request_items', 'display_planning_requests'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'submitted_at'),
            'classes': ('collapse',)
        }),
    )

    def display_planning_request_items(self, obj):
        """Display linked planning request items"""
        if obj.pk:
            items = obj.planning_request_items.all()
            if items.exists():
                return f'{items.count()} items from planning requests'
            return 'None'
        return '-'
    display_planning_request_items.short_description = 'Planning Items Count'

    def display_planning_requests(self, obj):
        """Display unique planning requests"""
        if obj.pk:
            items = obj.planning_request_items.select_related('planning_request').all()
            planning_requests = set(item.planning_request for item in items)
            if planning_requests:
                return ', '.join([f'{pr.request_number}' for pr in sorted(planning_requests, key=lambda x: x.request_number)])
            return 'None'
        return '-'
    display_planning_requests.short_description = 'Source Planning Requests'


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'unit')
    search_fields = ('code', 'name')  # Required for autocomplete
    list_filter = ('unit',)
    ordering = ('code',)