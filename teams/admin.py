from django.contrib import admin
from .models import Team


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'foreman', 'member_count', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'foreman__username', 'foreman__first_name', 'foreman__last_name']
    filter_horizontal = ['members']
    raw_id_fields = ['foreman']

    def member_count(self, obj):
        return obj.members.count()
    member_count.short_description = 'Üye Sayısı'
