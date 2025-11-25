from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from .models import (
    DepartmentRequest,
    PlanningRequest,
    PlanningRequestItem,
    FileAsset,
    FileAttachment,
    InventoryAllocation,
)


class FileAttachmentInline(GenericTabularInline):
    model = FileAttachment
    ct_field = 'content_type'
    ct_fk_field = 'object_id'
    extra = 0
    readonly_fields = ('uploaded_at', 'uploaded_by', 'source_attachment')
    fields = ('asset', 'description', 'source_attachment', 'uploaded_by', 'uploaded_at')
    raw_id_fields = ('asset', 'source_attachment')


@admin.register(DepartmentRequest)
class DepartmentRequestAdmin(admin.ModelAdmin):
    list_display = ('request_number', 'title', 'department', 'status', 'priority', 'requestor', 'needed_date', 'created_at')
    list_filter = ('status', 'department', 'priority', 'created_at')
    search_fields = ('request_number', 'title', 'description', 'department')
    readonly_fields = ('request_number', 'created_at', 'submitted_at', 'approved_by', 'approved_at')
    inlines = [FileAttachmentInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('request_number', 'title', 'description', 'department', 'needed_date', 'priority')
        }),
        ('Items', {
            'fields': ('items',)
        }),
        ('Request Details', {
            'fields': ('requestor', 'status')
        }),
        ('Approval Info', {
            'fields': ('approved_by', 'approved_at', 'rejection_reason'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'submitted_at'),
            'classes': ('collapse',)
        }),
    )


class PlanningRequestItemInline(admin.TabularInline):
    model = PlanningRequestItem
    extra = 1
    fields = ('item', 'job_no', 'quantity', 'quantity_from_inventory', 'quantity_to_purchase', 'priority', 'specifications', 'order')
    readonly_fields = ('quantity_from_inventory', 'quantity_to_purchase')
    autocomplete_fields = ['item']


@admin.register(PlanningRequest)
class PlanningRequestAdmin(admin.ModelAdmin):
    list_display = ('request_number', 'title', 'status', 'priority', 'check_inventory', 'inventory_control_completed', 'fully_from_inventory', 'created_by', 'needed_date', 'created_at')
    list_filter = ('status', 'priority', 'check_inventory', 'inventory_control_completed', 'fully_from_inventory', 'created_at')
    search_fields = ('request_number', 'title', 'description')
    readonly_fields = ('request_number', 'created_at', 'updated_at', 'ready_at', 'converted_at', 'completed_at', 'inventory_control_completed', 'fully_from_inventory', 'display_completion_stats', 'display_purchase_requests')
    inlines = [PlanningRequestItemInline, FileAttachmentInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('request_number', 'title', 'description', 'needed_date', 'priority')
        }),
        ('Source & Status', {
            'fields': ('department_request', 'status', 'created_by', 'display_completion_stats')
        }),
        ('Inventory Control', {
            'fields': ('check_inventory', 'inventory_control_completed', 'fully_from_inventory')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'ready_at', 'converted_at', 'completed_at'),
            'classes': ('collapse',)
        }),
        ('Purchase Requests', {
            'fields': ('display_purchase_requests',),
            'classes': ('collapse',)
        }),
    )

    def display_completion_stats(self, obj):
        """Display completion statistics"""
        if obj.pk:
            stats = obj.get_completion_stats()
            return f"{stats['converted_items']}/{stats['total_items']} items ({stats['completion_percentage']}%)"
        return '-'
    display_completion_stats.short_description = 'Completion'

    def display_purchase_requests(self, obj):
        """Display linked purchase requests via items"""
        if obj.pk:
            # Get unique purchase requests through items
            purchase_requests = set()
            for item in obj.items.all():
                for pr in item.purchase_requests.all():
                    purchase_requests.add(pr)

            if purchase_requests:
                return ', '.join([f'{pr.request_number}' for pr in sorted(purchase_requests, key=lambda x: x.request_number)])
            return 'None yet'
        return '-'
    display_purchase_requests.short_description = 'Related Purchase Requests'


@admin.register(PlanningRequestItem)
class PlanningRequestItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'planning_request', 'item', 'job_no', 'quantity', 'quantity_from_inventory', 'quantity_to_purchase', 'priority', 'display_converted_status')
    list_filter = ('priority', 'planning_request__status')
    search_fields = ('job_no', 'item__code', 'item__name')
    autocomplete_fields = ['item', 'planning_request']
    ordering = ('planning_request', 'order')
    inlines = [FileAttachmentInline]
    readonly_fields = ('quantity_from_inventory', 'quantity_to_purchase', 'display_purchase_requests', 'display_inventory_status')

    fieldsets = (
        ('Item Details', {
            'fields': ('planning_request', 'item', 'job_no', 'quantity', 'priority', 'specifications', 'order')
        }),
        ('Inventory Allocation', {
            'fields': ('quantity_from_inventory', 'quantity_to_purchase', 'display_inventory_status')
        }),
        ('Purchase Requests', {
            'fields': ('display_purchase_requests',),
            'classes': ('collapse',)
        }),
    )

    def display_converted_status(self, obj):
        """Show if item is converted to PR"""
        return '✓' if obj.is_converted else '✗'
    display_converted_status.short_description = 'Converted'
    display_converted_status.boolean = False

    def display_purchase_requests(self, obj):
        """Display linked purchase requests"""
        if obj.pk:
            prs = obj.purchase_requests.all()
            if prs.exists():
                return ', '.join([f'{pr.request_number}' for pr in prs])
            return 'Not converted yet'
        return '-'
    display_purchase_requests.short_description = 'Included in Purchase Requests'

    def display_inventory_status(self, obj):
        """Display inventory fulfillment status"""
        if obj.pk:
            if obj.is_fully_from_inventory:
                return '✓ Fully from inventory'
            elif obj.is_partially_from_inventory:
                return f'⚠ Partial: {obj.quantity_from_inventory} from inventory, {obj.quantity_to_purchase} to purchase'
            else:
                return '✗ Not from inventory'
        return '-'
    display_inventory_status.short_description = 'Inventory Status'


@admin.register(FileAsset)
class FileAssetAdmin(admin.ModelAdmin):
    list_display = ('id', 'file', 'uploaded_by', 'uploaded_at', 'description')
    list_filter = ('uploaded_at',)
    search_fields = ('file', 'description')
    readonly_fields = ('uploaded_at', 'uploaded_by')


@admin.register(FileAttachment)
class FileAttachmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'content_type', 'object_id', 'asset', 'uploaded_by', 'uploaded_at', 'source_attachment')
    list_filter = ('uploaded_at', 'content_type')
    search_fields = ('description',)
    readonly_fields = ('uploaded_at', 'uploaded_by')
    raw_id_fields = ('asset', 'source_attachment')


@admin.register(InventoryAllocation)
class InventoryAllocationAdmin(admin.ModelAdmin):
    list_display = ('id', 'planning_request_item', 'get_item_code', 'get_job_no', 'allocated_quantity', 'allocated_by', 'allocated_at')
    list_filter = ('allocated_at', 'allocated_by')
    search_fields = ('planning_request_item__item__code', 'planning_request_item__item__name', 'planning_request_item__job_no', 'notes')
    readonly_fields = ('allocated_at', 'allocated_by')
    autocomplete_fields = ['planning_request_item']
    ordering = ('-allocated_at',)

    fieldsets = (
        ('Allocation Details', {
            'fields': ('planning_request_item', 'allocated_quantity', 'notes')
        }),
        ('Tracking', {
            'fields': ('allocated_by', 'allocated_at')
        }),
    )

    def get_item_code(self, obj):
        """Display item code"""
        return obj.planning_request_item.item.code if obj.planning_request_item else '-'
    get_item_code.short_description = 'Item Code'
    get_item_code.admin_order_field = 'planning_request_item__item__code'

    def get_job_no(self, obj):
        """Display job number"""
        return obj.planning_request_item.job_no if obj.planning_request_item else '-'
    get_job_no.short_description = 'Job No'
    get_job_no.admin_order_field = 'planning_request_item__job_no'
