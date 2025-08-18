from django.contrib import admin
from .models import ApprovalPolicy, ApprovalStage, PRApprovalWorkflow, PRApprovalStageInstance, PRApprovalDecision

class ApprovalStageInline(admin.TabularInline):
    model = ApprovalStage
    extra = 0
    filter_horizontal = ["approver_users", "approver_groups"]

@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "min_amount_eur", "max_amount_eur", "selection_priority"]
    list_filter = ["is_active"]
    inlines = [ApprovalStageInline]

@admin.register(PRApprovalWorkflow)
class PRApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ["purchase_request", "policy", "current_stage_order", "is_complete", "is_rejected", "created_at"]
    readonly_fields = ["snapshot"]

@admin.register(PRApprovalStageInstance)
class PRApprovalStageInstanceAdmin(admin.ModelAdmin):
    list_display = ["workflow", "order", "name", "approved_count", "required_approvals", "is_complete", "is_rejected"]

@admin.register(PRApprovalDecision)
class PRApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = ["stage_instance", "approver", "decision", "decided_at"]
    readonly_fields = ["decided_at"]
