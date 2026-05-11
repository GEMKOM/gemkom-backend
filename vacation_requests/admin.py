from django.contrib import admin
from .models import UserLeaveBalance, VacationRequest


@admin.register(VacationRequest)
class VacationRequestAdmin(admin.ModelAdmin):
    list_display  = ["id", "requester", "leave_type", "start_date", "end_date", "duration_days", "status", "team", "created_at"]
    list_filter   = ["status", "leave_type", "team"]
    search_fields = ["requester__username", "requester__first_name", "requester__last_name", "reason"]
    readonly_fields = ["duration_days", "created_at", "updated_at"]
    ordering      = ["-created_at"]

    fieldsets = [
        (None, {"fields": ["requester", "team", "leave_type", "start_date", "end_date", "duration_days", "reason", "status"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"], "classes": ["collapse"]}),
    ]


@admin.register(UserLeaveBalance)
class UserLeaveBalanceAdmin(admin.ModelAdmin):
    list_display  = ["user", "total_days", "used_days", "remaining_days"]
    search_fields = ["user__username", "user__first_name", "user__last_name"]
    ordering      = ["user"]
    readonly_fields = ["used_days"]

    def remaining_days(self, obj):
        return obj.remaining_days
    remaining_days.short_description = "Kalan Gün"
