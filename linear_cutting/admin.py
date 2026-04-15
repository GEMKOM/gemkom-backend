from django.contrib import admin
from .models import LinearCuttingSession, LinearCuttingPart, LinearCuttingTask


class LinearCuttingPartInline(admin.TabularInline):
    model = LinearCuttingPart
    extra = 0


class LinearCuttingTaskInline(admin.TabularInline):
    model = LinearCuttingTask
    extra = 0
    fields = ['key', 'bar_index', 'material', 'stock_length_mm', 'waste_mm', 'completion_date']
    readonly_fields = ['key']


@admin.register(LinearCuttingSession)
class LinearCuttingSessionAdmin(admin.ModelAdmin):
    list_display = ['key', 'title', 'material', 'stock_length_mm', 'bars_needed', 'tasks_created', 'planning_request_created', 'created_by', 'created_at']
    list_filter = ['tasks_created', 'planning_request_created']
    search_fields = ['key', 'title', 'material']
    inlines = [LinearCuttingPartInline, LinearCuttingTaskInline]
    readonly_fields = ['key', 'created_at']


@admin.register(LinearCuttingPart)
class LinearCuttingPartAdmin(admin.ModelAdmin):
    list_display = ['id', 'session', 'label', 'nominal_length_mm', 'quantity', 'job_no']
    list_filter = ['session']
    search_fields = ['label', 'job_no', 'session__key']


@admin.register(LinearCuttingTask)
class LinearCuttingTaskAdmin(admin.ModelAdmin):
    list_display = ['key', 'session', 'bar_index', 'material', 'stock_length_mm', 'waste_mm', 'completion_date']
    list_filter = ['material']
    search_fields = ['key', 'session__key', 'material']
    readonly_fields = ['key']
