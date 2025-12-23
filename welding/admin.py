from django.contrib import admin
from .models import WeldingTimeEntry


@admin.register(WeldingTimeEntry)
class WeldingTimeEntryAdmin(admin.ModelAdmin):
    """
    Admin interface for WeldingTimeEntry.
    """
    list_display = [
        'id',
        'employee',
        'job_no',
        'date',
        'hours',
        'overtime_type',
        'get_overtime_multiplier',
        'created_at',
        'created_by',
    ]
    list_filter = [
        'overtime_type',
        'date',
        'employee',
        'created_at',
    ]
    search_fields = [
        'job_no',
        'employee__username',
        'employee__first_name',
        'employee__last_name',
        'description',
    ]
    readonly_fields = [
        'overtime_multiplier',
        'created_at',
        'created_by',
        'updated_at',
        'updated_by',
    ]
    date_hierarchy = 'date'
    ordering = ['-date', 'employee']

    def get_overtime_multiplier(self, obj):
        """Display overtime multiplier in list view."""
        return f"{obj.overtime_multiplier}x"
    get_overtime_multiplier.short_description = 'Multiplier'

    def save_model(self, request, obj, form, change):
        """Automatically set created_by/updated_by on save."""
        if not change:  # Creating new object
            obj.created_by = request.user
        else:  # Updating existing object
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)
