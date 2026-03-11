from django.contrib import admin
from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ['id', 'user', 'notification_type', 'title', 'is_read', 'is_emailed', 'created_at']
    list_filter   = ['notification_type', 'is_read', 'is_emailed']
    search_fields = ['user__username', 'user__email', 'title', 'body']
    readonly_fields = ['created_at', 'read_at', 'emailed_at']
    ordering      = ['-created_at']


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display  = ['user', 'notification_type', 'send_email', 'send_in_app']
    list_filter   = ['notification_type', 'send_email', 'send_in_app']
    search_fields = ['user__username']
