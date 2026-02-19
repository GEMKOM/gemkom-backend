from django.contrib import admin
from .models import (
    Subcontractor,
    SubcontractingPriceTier,
    SubcontractingAssignment,
    SubcontractorCostRecalcQueue,
    SubcontractorStatement,
    SubcontractorStatementLine,
    SubcontractorStatementAdjustment,
)


@admin.register(Subcontractor)
class SubcontractorAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'contact_person', 'phone', 'email', 'is_active']
    list_filter = ['is_active', 'default_currency']
    search_fields = ['name', 'short_name', 'tax_id']


class SubcontractingPriceTierInline(admin.TabularInline):
    model = SubcontractingPriceTier
    extra = 0
    readonly_fields = ['used_weight_kg', 'remaining_weight_kg', 'created_at']
    fields = ['name', 'price_per_kg', 'currency', 'allocated_weight_kg', 'used_weight_kg', 'remaining_weight_kg']


@admin.register(SubcontractingPriceTier)
class SubcontractingPriceTierAdmin(admin.ModelAdmin):
    list_display = ['job_order', 'name', 'price_per_kg', 'currency', 'allocated_weight_kg', 'remaining_weight_kg']
    list_filter = ['currency']
    search_fields = ['job_order__job_no', 'name']
    readonly_fields = ['used_weight_kg', 'remaining_weight_kg', 'created_at', 'updated_at']


@admin.register(SubcontractingAssignment)
class SubcontractingAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        'department_task', 'subcontractor', 'price_tier',
        'allocated_weight_kg', 'current_cost', 'cost_currency', 'last_billed_progress'
    ]
    list_filter = ['subcontractor', 'cost_currency']
    search_fields = ['department_task__job_order__job_no', 'subcontractor__name']
    readonly_fields = ['current_cost', 'cost_currency', 'last_billed_progress', 'created_at', 'updated_at']


@admin.register(SubcontractorCostRecalcQueue)
class SubcontractorCostRecalcQueueAdmin(admin.ModelAdmin):
    list_display = ['job_no', 'enqueued_at']


class SubcontractorStatementLineInline(admin.TabularInline):
    model = SubcontractorStatementLine
    extra = 0
    readonly_fields = [
        'assignment', 'job_no', 'job_title', 'subcontractor_name', 'price_tier_name',
        'allocated_weight_kg', 'previous_progress', 'current_progress',
        'delta_progress', 'effective_weight_kg', 'price_per_kg', 'cost_amount'
    ]
    can_delete = False


class SubcontractorStatementAdjustmentInline(admin.TabularInline):
    model = SubcontractorStatementAdjustment
    extra = 0
    fields = ['adjustment_type', 'amount', 'reason', 'description', 'job_order']


@admin.register(SubcontractorStatement)
class SubcontractorStatementAdmin(admin.ModelAdmin):
    list_display = [
        'subcontractor', 'year', 'month', 'status',
        'work_total', 'adjustment_total', 'grand_total', 'currency'
    ]
    list_filter = ['status', 'currency', 'subcontractor']
    search_fields = ['subcontractor__name']
    readonly_fields = [
        'work_total', 'adjustment_total', 'grand_total',
        'created_at', 'updated_at', 'submitted_at', 'approved_at'
    ]
    inlines = [SubcontractorStatementLineInline, SubcontractorStatementAdjustmentInline]
