from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework import serializers

from .models import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalStage,
    ApprovalStageInstance,
    ApprovalWorkflow,
)


# ---------------------------------------------------------------------------
# Policy & Stage
# ---------------------------------------------------------------------------

class ApprovalStageSerializer(serializers.ModelSerializer):
    approver_users_detail = serializers.SerializerMethodField()
    role_user_group_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStage
        fields = [
            "id", "order", "name", "required_approvals",
            "approver_users", "approver_users_detail",
            "climb_levels", "role_user_group", "role_user_group_name",
        ]

    def get_approver_users_detail(self, obj):
        return [
            {"id": u.id, "username": u.username, "full_name": u.get_full_name() or u.username}
            for u in obj.approver_users.select_related().all()
        ]

    def get_role_user_group_name(self, obj):
        if obj.role_user_group_id:
            return obj.role_user_group.name
        return None


class ApprovalStageWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalStage
        fields = [
            "id", "order", "name", "required_approvals",
            "approver_users", "climb_levels", "role_user_group",
        ]

    def validate(self, attrs):
        climb = attrs.get("climb_levels", getattr(self.instance, "climb_levels", None))
        group = attrs.get("role_user_group", getattr(self.instance, "role_user_group", None))
        if climb and group:
            raise serializers.ValidationError(
                "climb_levels and role_user_group are mutually exclusive; "
                "role_user_group takes priority when both are set."
            )
        return attrs


class ApprovalPolicySerializer(serializers.ModelSerializer):
    stages = ApprovalStageSerializer(many=True, read_only=True)
    live_workflow_count = serializers.SerializerMethodField()
    total_workflow_count = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalPolicy
        fields = [
            "id", "name", "is_active", "selection_priority",
            "min_amount_eur", "max_amount_eur",
            "subject_type",
            "live_workflow_count", "total_workflow_count",
            "stages",
        ]

    def get_live_workflow_count(self, obj):
        return obj.approvalworkflow_set.filter(
            is_complete=False, is_rejected=False, is_cancelled=False
        ).count()

    def get_total_workflow_count(self, obj):
        return obj.approvalworkflow_set.count()


class ApprovalPolicyWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalPolicy
        fields = [
            "id", "name", "is_active", "selection_priority",
            "min_amount_eur", "max_amount_eur",
            "subject_type",
        ]


# ---------------------------------------------------------------------------
# Live workflows (read-only — for the approval audit / inbox view)
# ---------------------------------------------------------------------------

class DecisionDetailSerializer(serializers.ModelSerializer):
    approver_username = serializers.CharField(source="approver.username", read_only=True)
    approver_full_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalDecision
        fields = ["id", "approver", "approver_username", "approver_full_name",
                  "decision", "comment", "decided_at"]

    def get_approver_full_name(self, obj):
        return obj.approver.get_full_name() or obj.approver.username


class StageInstanceDetailSerializer(serializers.ModelSerializer):
    decisions = DecisionDetailSerializer(many=True, read_only=True)
    approvers_detail = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStageInstance
        fields = [
            "id", "order", "name", "required_approvals", "approved_count",
            "is_complete", "is_rejected",
            "approver_user_ids", "approvers_detail",
            "decisions",
        ]

    def get_approvers_detail(self, obj):
        ids = obj.approver_user_ids or []
        if not ids:
            return []
        users = User.objects.filter(id__in=ids).only("id", "username", "first_name", "last_name")
        by_id = {u.id: u for u in users}
        return [
            {"id": i, "username": by_id[i].username, "full_name": by_id[i].get_full_name() or by_id[i].username}
            for i in ids if i in by_id
        ]


class WorkflowDetailSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(source="policy.name", read_only=True)
    subject_type = serializers.SerializerMethodField()
    stage_instances = StageInstanceDetailSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalWorkflow
        fields = [
            "id", "policy", "policy_name",
            "subject_type", "object_id",
            "current_stage_order",
            "is_complete", "is_rejected", "is_cancelled",
            "created_at", "snapshot",
            "stage_instances",
        ]

    def get_subject_type(self, obj):
        return f"{obj.content_type.app_label}.{obj.content_type.model}"
