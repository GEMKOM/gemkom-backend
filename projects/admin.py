from django.contrib import admin
from .models import Customer, JobOrder


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
