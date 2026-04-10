from django.contrib import admin

from .models import AttendanceSite, AttendanceRecord, ShiftRule


@admin.register(AttendanceSite)
class AttendanceSiteAdmin(admin.ModelAdmin):
    list_display = ['name', 'latitude', 'longitude', 'radius_meters']


@admin.register(ShiftRule)
class ShiftRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'work_location', 'expected_start', 'expected_end',
                    'overtime_threshold_minutes', 'is_active']
    list_filter = ['work_location', 'is_active']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'check_in_time', 'check_out_time',
                    'method', 'status', 'overtime_hours']
    list_filter = ['status', 'method', 'date']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    raw_id_fields = ['user', 'reviewed_by']
    date_hierarchy = 'date'
    ordering = ['-date', '-check_in_time']
