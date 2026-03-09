from django.contrib import admin

from .models import OvertimeEntry, OvertimeRequest


class OvertimeEntryInline(admin.TabularInline):
    model = OvertimeEntry
    extra = 0
    fields = ("user", "job_no", "description", "approved_hours", "created_at")
    readonly_fields = ("created_at",)


@admin.register(OvertimeRequest)
class OvertimeRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "requester", "team", "start_at", "end_at", "duration_hours", "status", "created_at")
    list_filter = ("status", "team")
    search_fields = ("requester__username", "requester__first_name", "requester__last_name", "team", "reason")
    readonly_fields = ("duration_hours", "created_at", "updated_at")
    inlines = [OvertimeEntryInline]


@admin.register(OvertimeEntry)
class OvertimeEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "request", "user", "job_no", "approved_hours", "created_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "job_no")
    list_filter = ("request__status",)
