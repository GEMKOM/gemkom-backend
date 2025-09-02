# approvals/admin.py
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils.html import format_html
from django.urls import reverse

from .models import ApprovalPolicy, ApprovalStage  # your existing policy models
from .models import (
    ApprovalWorkflow, ApprovalStageInstance, ApprovalDecision
)

# ---------- Policy & Stages ----------

class ApprovalStageInline(admin.TabularInline):
    model = ApprovalStage
    extra = 0
    fields = ("order", "name", "required_approvals", "approver_users", "approver_groups")
    filter_horizontal = ("approver_users", "approver_groups")
    ordering = ("order",)

@admin.register(ApprovalPolicy)
class ApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "selection_priority")
    list_filter = ("is_active",)
    search_fields = ("name",)
    inlines = [ApprovalStageInline]
    ordering = ("selection_priority", "id")


# ---------- Workflow + Stage Instances ----------

class StageInstanceInline(admin.TabularInline):
    model = ApprovalStageInstance
    extra = 0
    fields = (
        "order", "name", "required_approvals",
        "approved_count", "is_complete", "is_rejected",
        "approver_user_ids", "approver_group_ids",
    )
    readonly_fields = ("approved_count",)
    ordering = ("order",)

@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "subject_ct",
        "object_id",        # ✅ use object_id (real field) instead of subject_id
        "subject_link",
        "policy",
        "current_stage_order",
        "is_complete",
        "is_rejected",
        "is_cancelled",
        "created_at",
    )
    list_filter = ("is_complete", "is_rejected", "is_cancelled", "policy")
    search_fields = ("object_id", "policy__name")
    date_hierarchy = "created_at"
    inlines = [StageInstanceInline]
    readonly_fields = ("created_at",)

    @admin.display(description="Subject type")
    def subject_ct(self, obj: ApprovalWorkflow):
        return f"{obj.content_type.app_label}.{obj.content_type.model}"

    @admin.display(description="Subject")
    def subject_link(self, obj: ApprovalWorkflow):
        subj = obj.subject
        if not subj:
            return "-"
        label = str(subj)
        # try to link to admin page of subject if possible
        try:
            ct: ContentType = obj.content_type
            url = reverse(f"admin:{ct.app_label}_{ct.model}_change", args=[obj.object_id])
            return format_html('<a href="{}">{}</a>', url, label)
        except Exception:
            return label



@admin.register(ApprovalStageInstance)
class ApprovalStageInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "id", "workflow", "order", "name",
        "required_approvals", "approved_count",
        "is_complete", "is_rejected",
    )
    list_filter = ("is_complete", "is_rejected", "workflow__policy")
    search_fields = ("name", "workflow__id")
    ordering = ("workflow", "order")


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "stage_instance", "approver",
        "decision", "decided_at",
    )
    list_filter = ("decision", "decided_at")
    search_fields = ("approver__username", "approver__first_name", "approver__last_name")
    date_hierarchy = "decided_at"
    ordering = ("-decided_at",)
