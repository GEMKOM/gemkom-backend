from django.contrib import admin
from .models import Customer


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
