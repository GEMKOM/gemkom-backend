from django.contrib import admin
from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'short_name', 'is_active', 'default_currency', 'created_at']
    list_filter = ['is_active', 'default_currency']
    search_fields = ['code', 'name', 'short_name', 'contact_person', 'email']
    ordering = ['name']
    readonly_fields = ['created_at', 'created_by', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('code', 'name', 'short_name', 'is_active')
        }),
        ('İletişim Bilgileri', {
            'fields': ('contact_person', 'phone', 'email', 'address')
        }),
        ('Vergi Bilgileri', {
            'fields': ('tax_id', 'tax_office')
        }),
        ('Tercihler', {
            'fields': ('default_currency', 'notes')
        }),
        ('Sistem Bilgileri', {
            'fields': ('created_at', 'created_by', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class JobOrderFileInline(admin.TabularInline):
    model = JobOrderFile
    extra = 0
    fields = ['file', 'file_type', 'name', 'description', 'uploaded_at', 'uploaded_by']
    readonly_fields = ['uploaded_at', 'uploaded_by']


@admin.register(JobOrder)
class JobOrderAdmin(admin.ModelAdmin):
    list_display = [
        'job_no', 'title', 'customer', 'status', 'priority',
        'completion_percentage', 'target_completion_date', 'created_at'
    ]
    list_filter = ['status', 'priority', 'customer', 'cost_currency']
    search_fields = ['job_no', 'title', 'description', 'customer__name', 'customer__code']
    ordering = ['-created_at']
    readonly_fields = [
        'started_at', 'completed_at', 'labor_cost', 'material_cost',
        'subcontractor_cost', 'total_cost', 'last_cost_calculation',
        'completion_percentage', 'created_at', 'created_by',
        'updated_at', 'completed_by'
    ]
    autocomplete_fields = ['customer', 'parent']
    raw_id_fields = ['created_by', 'completed_by']
    inlines = [JobOrderFileInline]

    fieldsets = (
        (None, {
            'fields': ('job_no', 'title', 'description', 'customer', 'customer_order_no')
        }),
        ('Hiyerarşi', {
            'fields': ('parent',),
            'classes': ('collapse',)
        }),
        ('Durum', {
            'fields': ('status', 'priority')
        }),
        ('Zaman Çizelgesi', {
            'fields': ('target_completion_date', 'started_at', 'completed_at')
        }),
        ('Maliyet', {
            'fields': (
                'estimated_cost', 'cost_currency',
                ('labor_cost', 'material_cost', 'subcontractor_cost'),
                'total_cost', 'last_cost_calculation'
            ),
            'classes': ('collapse',)
        }),
        ('İlerleme', {
            'fields': ('completion_percentage',)
        }),
        ('Sistem Bilgileri', {
            'fields': ('created_at', 'created_by', 'updated_at', 'completed_by'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(JobOrderFile)
class JobOrderFileAdmin(admin.ModelAdmin):
    list_display = ['name', 'job_order', 'file_type', 'uploaded_at', 'uploaded_by']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['name', 'description', 'job_order__job_no', 'job_order__title']
    ordering = ['-uploaded_at']
    readonly_fields = ['uploaded_at', 'uploaded_by']
    autocomplete_fields = ['job_order']

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


# =============================================================================
# Department Task Template Admin
# =============================================================================

class DepartmentTaskTemplateItemInline(admin.TabularInline):
    model = DepartmentTaskTemplateItem
    extra = 1
    fk_name = 'template'
    fields = ['department', 'title', 'sequence', 'parent']
    ordering = ['sequence']

    def get_queryset(self, request):
        # Show all items, but they're grouped by parent in the inline
        return super().get_queryset(request)


@admin.register(DepartmentTaskTemplateItem)
class DepartmentTaskTemplateItemAdmin(admin.ModelAdmin):
    """Standalone admin for managing template items with hierarchy."""
    list_display = ['title', 'template', 'department', 'sequence', 'parent']
    list_filter = ['template', 'department']
    search_fields = ['title', 'template__name']
    ordering = ['template', 'sequence']
    autocomplete_fields = ['template', 'parent']
    filter_horizontal = ['depends_on']

    fieldsets = (
        (None, {
            'fields': ('template', 'department', 'title', 'sequence')
        }),
        ('Hiyerarşi', {
            'fields': ('parent',),
            'description': 'Alt öğe oluşturmak için üst öğeyi seçin. Alt öğeler üst öğenin departmanını miras alır.'
        }),
        ('Bağımlılıklar', {
            'fields': ('depends_on',),
            'classes': ('collapse',),
            'description': 'Bu görev ancak seçilen görevler tamamlandığında başlatılabilir.'
        }),
    )


@admin.register(DepartmentTaskTemplate)
class DepartmentTaskTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'is_default', 'items_count', 'created_at']
    list_filter = ['is_active', 'is_default']
    search_fields = ['name', 'description']
    ordering = ['name']
    readonly_fields = ['created_at', 'created_by', 'updated_at']
    inlines = [DepartmentTaskTemplateItemInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_active', 'is_default')
        }),
        ('Sistem Bilgileri', {
            'fields': ('created_at', 'created_by', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def items_count(self, obj):
        return obj.items.count()
    items_count.short_description = 'Öğe Sayısı'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# =============================================================================
# Job Order Department Task Admin
# =============================================================================

class DepartmentTaskSubtaskInline(admin.TabularInline):
    model = JobOrderDepartmentTask
    fk_name = 'parent'
    extra = 0
    fields = ['title', 'status', 'assigned_to', 'target_completion_date']
    readonly_fields = ['status']
    verbose_name = 'Alt Görev'
    verbose_name_plural = 'Alt Görevler'


@admin.register(JobOrderDepartmentTask)
class JobOrderDepartmentTaskAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'job_order', 'department', 'status', 'assigned_to',
        'sequence', 'created_at'
    ]
    list_filter = ['status', 'department', 'job_order']
    search_fields = ['title', 'description', 'job_order__job_no', 'job_order__title']
    ordering = ['job_order', 'sequence']
    readonly_fields = [
        'started_at', 'completed_at',
        'created_at', 'created_by', 'updated_at', 'completed_by'
    ]
    autocomplete_fields = ['job_order', 'assigned_to', 'parent']
    raw_id_fields = ['created_by', 'completed_by']
    filter_horizontal = ['depends_on']
    inlines = [DepartmentTaskSubtaskInline]

    fieldsets = (
        (None, {
            'fields': ('job_order', 'department', 'title', 'description', 'sequence')
        }),
        ('Hiyerarşi', {
            'fields': ('parent',),
            'classes': ('collapse',)
        }),
        ('Durum', {
            'fields': ('status', 'assigned_to')
        }),
        ('Zaman Çizelgesi', {
            'fields': ('target_start_date', 'target_completion_date', 'started_at', 'completed_at')
        }),
        ('Bağımlılıklar', {
            'fields': ('depends_on',),
            'classes': ('collapse',)
        }),
        ('Notlar', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Sistem Bilgileri', {
            'fields': ('created_at', 'created_by', 'updated_at', 'completed_by'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
