from django.contrib import admin

from .models import AttendanceLeaveInterval, AttendanceSite, AttendanceRecord, AttendanceSession, ShiftRule, PublicHoliday


class SessionInline(admin.TabularInline):
    model = AttendanceSession
    extra = 0
    fields = ['check_in_time', 'check_out_time', 'method', 'status', 'client_ip', 'override_reason']
    readonly_fields = ['created_at', 'updated_at']


class LeaveIntervalInline(admin.TabularInline):
    model = AttendanceLeaveInterval
    extra = 0
    fields = ['start_time', 'end_time', 'leave_type', 'notes']


@admin.register(AttendanceSite)
class AttendanceSiteAdmin(admin.ModelAdmin):
    list_display = ['name', 'latitude', 'longitude', 'radius_meters']


@admin.register(ShiftRule)
class ShiftRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'expected_start', 'expected_end',
                    'overtime_threshold_minutes', 'is_active', 'is_default']
    list_filter = ['is_active', 'is_default']


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ['date', 'local_name', 'name', 'is_half_day']
    list_filter = ['date', 'is_half_day']
    search_fields = ['local_name', 'name']
    date_hierarchy = 'date'
    ordering = ['date']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status', 'total_present_minutes',
                    'late_minutes', 'early_leave_minutes', 'overtime_minutes']
    list_filter = ['status', 'date']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']
    raw_id_fields = ['user', 'reviewed_by']
    date_hierarchy = 'date'
    ordering = ['-date']
    readonly_fields = ['total_present_minutes', 'late_minutes', 'early_leave_minutes', 'overtime_minutes']
    inlines = [SessionInline, LeaveIntervalInline]


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ['record', 'check_in_time', 'check_out_time', 'method', 'status', 'client_ip']
    list_filter = ['status', 'method']
    search_fields = ['record__user__username', 'record__user__first_name', 'record__user__last_name']
    raw_id_fields = ['record']
    ordering = ['-check_in_time']
