from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from django.contrib.auth import get_user_model

from approvals.models import ApprovalWorkflow
from approvals.serializers import WorkflowSerializer
from users.helpers import primary_team_from_groups, TEAM_LABELS

from .models import LEAVE_TYPE_CHOICES, VacationRequest, UserLeaveBalance

User = get_user_model()


class VacationRequestListSerializer(serializers.ModelSerializer):
    requester_username  = serializers.CharField(source="requester.username", read_only=True)
    requester_full_name = serializers.SerializerMethodField()
    status_label        = serializers.SerializerMethodField()
    leave_type_label    = serializers.SerializerMethodField()
    team_label          = serializers.SerializerMethodField()
    approval            = serializers.SerializerMethodField()

    def get_requester_full_name(self, obj):
        return obj.requester.get_full_name() or obj.requester.username

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_leave_type_label(self, obj):
        return dict(LEAVE_TYPE_CHOICES).get(obj.leave_type, obj.leave_type)

    def get_team_label(self, obj):
        return TEAM_LABELS.get(obj.team, obj.team or "")

    def get_approval(self, obj):
        wfs = getattr(obj, "approvals", None)
        if wfs is not None:
            wf = wfs.order_by("-created_at").first()
        else:
            ct = ContentType.objects.get_for_model(VacationRequest)
            wf = ApprovalWorkflow.objects.filter(content_type=ct, object_id=obj.id).order_by("-created_at").first()
        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    class Meta:
        model = VacationRequest
        fields = [
            "id", "status", "status_label",
            "leave_type", "leave_type_label",
            "start_date", "end_date", "duration_days",
            "requester", "requester_username", "requester_full_name",
            "team", "team_label",
            "created_at", "approval",
        ]


class VacationRequestDetailSerializer(serializers.ModelSerializer):
    requester_username  = serializers.CharField(source="requester.username", read_only=True)
    requester_full_name = serializers.SerializerMethodField()
    status_label        = serializers.SerializerMethodField()
    leave_type_label    = serializers.SerializerMethodField()
    team_label          = serializers.SerializerMethodField()
    approval            = serializers.SerializerMethodField()

    def get_requester_full_name(self, obj):
        return obj.requester.get_full_name() or obj.requester.username

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_leave_type_label(self, obj):
        return dict(LEAVE_TYPE_CHOICES).get(obj.leave_type, obj.leave_type)

    def get_team_label(self, obj):
        return TEAM_LABELS.get(obj.team, obj.team or "")

    def get_approval(self, obj):
        wfs = getattr(obj, "approvals", None)
        if wfs is not None:
            wf = wfs.order_by("-created_at").first()
        else:
            ct = ContentType.objects.get_for_model(VacationRequest)
            wf = ApprovalWorkflow.objects.filter(content_type=ct, object_id=obj.id).order_by("-created_at").first()
        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    class Meta:
        model = VacationRequest
        fields = [
            "id", "status", "status_label",
            "leave_type", "leave_type_label",
            "start_date", "end_date", "duration_days",
            "requester", "requester_username", "requester_full_name",
            "team", "team_label",
            "reason", "created_at", "updated_at", "approval",
        ]


class VacationRequestCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VacationRequest
        fields = ["leave_type", "start_date", "end_date", "reason"]

    def validate(self, data):
        start = data.get("start_date")
        end   = data.get("end_date")
        if start and end and end < start:
            raise serializers.ValidationError("end_date must be on or after start_date.")
        return data

    def _validate_overlaps(self, requester, start_date, end_date, instance=None):
        qs = VacationRequest.objects.filter(
            requester=requester,
            status__in=[VacationRequest.STATUS_SUBMITTED, VacationRequest.STATUS_APPROVED],
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Bu tarihler arasında zaten onay bekleyen veya onaylanmış bir izin talebiniz bulunmaktadır."
            )

    def create(self, validated_data):
        requester = self.context["request"].user
        start_date = validated_data["start_date"]
        end_date   = validated_data["end_date"]

        self._validate_overlaps(requester, start_date, end_date)

        team = primary_team_from_groups(requester) or ""

        vr = VacationRequest.objects.create(requester=requester, team=team, **validated_data)
        vr.send_for_approval()
        return vr


class VacationRequestUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VacationRequest
        fields = ["reason"]

    def validate(self, attrs):
        if self.instance.status != VacationRequest.STATUS_SUBMITTED:
            raise serializers.ValidationError("Yalnızca onay bekleyen talepler düzenlenebilir.")
        return attrs


class UserLeaveBalanceSerializer(serializers.ModelSerializer):
    remaining_days      = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)
    leave_type_label    = serializers.SerializerMethodField()
    user_username       = serializers.CharField(source="user.username", read_only=True)
    user_full_name      = serializers.SerializerMethodField()

    def get_leave_type_label(self, obj):
        return dict(LEAVE_TYPE_CHOICES).get(obj.leave_type, obj.leave_type)

    def get_user_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    class Meta:
        model = UserLeaveBalance
        fields = [
            "id", "user", "user_username", "user_full_name",
            "year", "leave_type", "leave_type_label",
            "total_days", "used_days", "remaining_days",
        ]
        read_only_fields = ["id", "user", "user_username", "user_full_name", "used_days", "remaining_days"]
