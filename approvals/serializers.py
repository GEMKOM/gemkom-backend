from rest_framework import serializers
from .models import PRApprovalWorkflow, PRApprovalStageInstance, PRApprovalDecision
from django.contrib.auth.models import User


class MiniUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        fn = (obj.first_name or "").strip()
        ln = (obj.last_name or "").strip()
        return (fn + " " + ln).strip()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "full_name"]

class DecisionSerializer(serializers.ModelSerializer):
    approver_detail = MiniUserSerializer(source="approver", read_only=True)

    class Meta:
        model = PRApprovalDecision
        fields = ["id", "approver", "approver_detail", "decision", "comment", "decided_at"]


class StageInstanceSerializer(serializers.ModelSerializer):
    decisions = DecisionSerializer(many=True, read_only=True)
    approvers = serializers.SerializerMethodField()

    class Meta:
        model = PRApprovalStageInstance
        fields = [
            "order", "name",
            "required_approvals", "approved_count",
            "is_complete", "is_rejected",
            "approver_user_ids",   # keep for backward compatibility
            "approvers",           # NEW: rich user objects
            "decisions",
        ]

    def get_approvers(self, obj):
        # try cache first (populated by WorkflowSerializer.get_stage_instances)
        cache = (self.context or {}).get("user_cache", {})
        ids = obj.approver_user_ids or []
        users = []
        missing = []
        for uid in ids:
            u = cache.get(uid)
            if u is not None:
                users.append(u)
            else:
                missing.append(uid)
        if missing:
            qs = User.objects.filter(id__in=missing).only("id","username","first_name","last_name")
            # update cache so siblings reuse it
            for u in qs:
                ser = MiniUserSerializer(u).data
                cache[u.id] = ser
                users.append(ser)
            # write back to context so siblings see it
            self.context["user_cache"] = cache
        # preserve the same order as approver_user_ids
        by_id = {u["id"]: u for u in users}
        return [by_id[i] for i in ids if i in by_id]


class WorkflowSerializer(serializers.ModelSerializer):
    stage_instances = serializers.SerializerMethodField()

    class Meta:
        model = PRApprovalWorkflow
        fields = ["policy", "current_stage_order", "is_complete", "is_rejected", "stage_instances"]

    def get_stage_instances(self, obj):
        stages = list(obj.stage_instances.all().order_by("order"))

        # collect all approver ids once
        ids = set()
        for s in stages:
            for uid in (s.approver_user_ids or []):
                ids.add(uid)

        # prefetch users into cache
        user_cache = {}
        if ids:
            qs = User.objects.filter(id__in=list(ids)).only("id","username","first_name","last_name")
            for u in qs:
                user_cache[u.id] = MiniUserSerializer(u).data

        ctx = dict(self.context or {})
        ctx["user_cache"] = user_cache

        return StageInstanceSerializer(stages, many=True, context=ctx).data






