from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers
from django.contrib.auth import get_user_model

from approvals.models import ApprovalWorkflow
from approvals.serializers import WorkflowSerializer
from users.helpers import primary_team_from_groups, TEAM_LABELS

from .models import LEAVE_TYPE_CHOICES, UserLeaveBalance, VacationRequest

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
            "start_date", "end_date", "start_time", "end_time", "duration_days",
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
            "start_date", "end_date", "start_time", "end_time", "duration_days",
            "requester", "requester_username", "requester_full_name",
            "team", "team_label",
            "reason", "created_at", "updated_at", "approval",
        ]


class VacationRequestCreateSerializer(serializers.ModelSerializer):
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time   = serializers.TimeField(required=False, allow_null=True)

    class Meta:
        model = VacationRequest
        fields = ["leave_type", "start_date", "end_date", "start_time", "end_time", "reason"]

    def validate(self, data):
        from .models import LEAVE_COMPENSATORY
        start = data.get("start_date")
        end   = data.get("end_date")

        if start and end and end < start:
            raise serializers.ValidationError("end_date must be on or after start_date.")

        if data.get("leave_type") == LEAVE_COMPENSATORY:
            start_time = data.get("start_time")
            end_time   = data.get("end_time")
            if not start_time or not end_time:
                raise serializers.ValidationError(
                    "Mazeret izni için başlangıç ve bitiş saati zorunludur."
                )
            if start and end and end != start:
                raise serializers.ValidationError(
                    "Mazeret izni yalnızca tek bir gün için geçerlidir."
                )
            if end_time <= start_time:
                raise serializers.ValidationError(
                    "Bitiş saati başlangıç saatinden sonra olmalıdır."
                )
        else:
            # Non-compensatory leaves must not have times
            data.pop("start_time", None)
            data.pop("end_time", None)

        return data

    def _validate_overlaps(self, requester, start_date, end_date, leave_type, start_time=None, end_time=None, instance=None):
        from .models import LEAVE_COMPENSATORY

        if leave_type == LEAVE_COMPENSATORY:
            # For compensatory, check time overlap on the same day
            from datetime import datetime
            existing = VacationRequest.objects.filter(
                requester=requester,
                leave_type=LEAVE_COMPENSATORY,
                status__in=[VacationRequest.STATUS_SUBMITTED, VacationRequest.STATUS_APPROVED],
                start_date=start_date,
            )
            if instance:
                existing = existing.exclude(pk=instance.pk)
            for ex in existing:
                if ex.start_time < end_time and ex.end_time > start_time:
                    raise serializers.ValidationError(
                        "Bu saatler arasında zaten onay bekleyen veya onaylanmış bir mazeret izni bulunmaktadır."
                    )
        else:
            qs = VacationRequest.objects.filter(
                requester=requester,
                status__in=[VacationRequest.STATUS_SUBMITTED, VacationRequest.STATUS_APPROVED],
                start_date__lte=end_date,
                end_date__gte=start_date,
            ).exclude(leave_type=LEAVE_COMPENSATORY)
            if instance:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "Bu tarihler arasında zaten onay bekleyen veya onaylanmış bir izin talebiniz bulunmaktadır."
                )

    def create(self, validated_data):
        from .models import LEAVE_COMPENSATORY
        requester  = self.context["request"].user
        start_date = validated_data["start_date"]
        end_date   = validated_data["end_date"]
        leave_type = validated_data["leave_type"]
        start_time = validated_data.get("start_time")
        end_time   = validated_data.get("end_time")

        self._validate_overlaps(requester, start_date, end_date, leave_type, start_time, end_time)

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


class UserLeaveSetupSerializer(serializers.Serializer):
    """
    Read/write hire_date, birth_date (UserProfile) and total_days (UserLeaveBalance) together.
    HR-only. GET returns current values, PATCH updates atomically.
    """
    user_id        = serializers.IntegerField(read_only=True)
    username       = serializers.CharField(read_only=True)
    full_name      = serializers.CharField(read_only=True)
    hire_date      = serializers.DateField(allow_null=True, required=False)
    birth_date     = serializers.DateField(allow_null=True, required=False)
    total_days     = serializers.DecimalField(max_digits=6, decimal_places=1, required=False)
    used_days      = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)
    remaining_days = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)


class UserLeaveBalanceSerializer(serializers.ModelSerializer):
    remaining_days = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)
    user_username  = serializers.CharField(source="user.username", read_only=True)
    user_full_name = serializers.SerializerMethodField()

    def get_user_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    class Meta:
        model = UserLeaveBalance
        fields = [
            "id", "user", "user_username", "user_full_name",
            "total_days", "used_days", "remaining_days",
        ]
        read_only_fields = ["id", "user", "user_username", "user_full_name", "used_days", "remaining_days"]
