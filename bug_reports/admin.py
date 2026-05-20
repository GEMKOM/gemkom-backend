from django.contrib import admin
from .models import BugReport, BugReportAttachment, BugReportMessage


class BugReportMessageInline(admin.TabularInline):
    model = BugReportMessage
    extra = 0
    readonly_fields = ['sender_type', 'sender', 'content', 'created_at']


class BugReportAttachmentInline(admin.TabularInline):
    model = BugReportAttachment
    extra = 0
    readonly_fields = ['file', 'uploaded_by', 'uploaded_at']


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display  = ['id', 'title', 'reported_by', 'status', 'repo_target', 'created_at']
    list_filter   = ['status', 'repo_target']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at', 'closed_at']
    inlines       = [BugReportMessageInline, BugReportAttachmentInline]
