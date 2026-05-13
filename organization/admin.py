from django.contrib import admin
from .models import Position


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'title', 'level', 'department_code', 'parent', 'is_active', 'holder_count']
    list_filter = ['level', 'department_code', 'is_active']
    search_fields = ['title', 'department_code']
    raw_id_fields = ['parent']
    filter_horizontal = ['permissions']
    ordering = ['level', 'department_code', 'title']

    def holder_count(self, obj):
        return obj.holders.filter(user__is_active=True).count()
    holder_count.short_description = 'Holders'
