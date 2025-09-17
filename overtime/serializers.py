# overtime/serializers.py
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from approvals.models import ApprovalWorkflow
from approvals.serializers import WorkflowSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model

from users.models import UserProfile

from .models import OvertimeRequest, OvertimeEntry

User = get_user_model()
TEAM_LABELS = dict(UserProfile._meta.get_field("team").choices)

class OvertimeEntryReadSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = OvertimeEntry
        fields = ["id", "user_id", "user_username", "user_full_name", "job_no", "description", "approved_hours", "created_at"]

    def get_user_full_name(self, obj):
        return getattr(obj.user, "get_full_name", lambda: "")() or obj.user.username


class OvertimeEntryWriteSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    class Meta:
        model = OvertimeEntry
        fields = ["user", "job_no", "description"]


class OvertimeRequestListSerializer(serializers.ModelSerializer):
    requester_username = serializers.CharField(source="requester.username", read_only=True)
    total_users = serializers.IntegerField(source="entries.count", read_only=True)
    status_label = serializers.SerializerMethodField()
    team_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()

    def get_status_label(self, obj):
        return obj.get_status_display()
    
    def get_team_label(self, obj):
        return TEAM_LABELS.get(obj.team, obj.team or "")
    
    def get_approval(self, obj):
        """
        Return the latest workflow for this overtime request (if any).
        Uses prefetched GenericRelation if present; otherwise falls back to a direct query.
        """
        wfs = getattr(obj, "approvals", None)  # GenericRelation (see step 2)
        if wfs is not None:
            wf = wfs.order_by("-created_at").first()
        else:
            ct = ContentType.objects.get_for_model(OvertimeRequest)
            wf = (ApprovalWorkflow.objects
                  .filter(content_type=ct, object_id=obj.id)
                  .order_by("-created_at")
                  .first())
        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    class Meta:
        model = OvertimeRequest
        fields = [
            "id", "status", "status_label", "start_at", "end_at", "duration_hours",
            "requester", "requester_username", "team", "team_label", "total_users", "created_at","approval"
        ]


class OvertimeRequestDetailSerializer(serializers.ModelSerializer):
    requester_username = serializers.CharField(source="requester.username", read_only=True)
    entries = OvertimeEntryReadSerializer(many=True, read_only=True)
    status_label = serializers.SerializerMethodField()
    team_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()

    def get_status_label(self, obj):
        return obj.get_status_display()
    
    def get_team_label(self, obj):
        return TEAM_LABELS.get(obj.team, obj.team or "")
    
    def get_approval(self, obj):
        """
        Return the latest workflow for this overtime request (if any).
        Uses prefetched GenericRelation if present; otherwise falls back to a direct query.
        """
        wfs = getattr(obj, "approvals", None)  # GenericRelation (see step 2)
        if wfs is not None:
            wf = wfs.order_by("-created_at").first()
        else:
            ct = ContentType.objects.get_for_model(OvertimeRequest)
            wf = (ApprovalWorkflow.objects
                  .filter(content_type=ct, object_id=obj.id)
                  .order_by("-created_at")
                  .first())
        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    class Meta:
        model = OvertimeRequest
        fields = [
            "id", "status", "start_at", "end_at", "duration_hours",
            "requester", "requester_username", "team", "reason",
            "entries", "created_at", "updated_at", "team_label", "status_label", "approval"
        ]


class OvertimeRequestCreateSerializer(serializers.ModelSerializer):
    """
    Create payload includes:
    - start_at, end_at
    - reason (optional)
    - entries: [{user: <id>, job_no: "...", description: "..."}, ...]
    """
    entries = OvertimeEntryWriteSerializer(many=True)

    class Meta:
        model = OvertimeRequest
        fields = ["start_at", "end_at", "reason", "entries"]

    def validate(self, data):
        start_at = data["start_at"]
        end_at = data["end_at"]
        if end_at <= start_at:
            raise serializers.ValidationError("end_at must be after start_at.")
        return data

    def _validate_overlaps(self, *, requester, start_at, end_at, entries_users, instance=None):
        """
        Disallow overlapping open/approved requests for the same user & time range.
        """
        qs = OvertimeRequest.objects.filter(
            status__in=["submitted", "approved"],
            entries__user__in=entries_users,
        ).distinct()

        if instance:
            qs = qs.exclude(pk=instance.pk)

        # overlap condition: existing.start < new.end AND existing.end > new.start
        qs = qs.filter(Q(start_at__lt=end_at) & Q(end_at__gt=start_at))
        if qs.exists():
            raise serializers.ValidationError("Bir veya daha fazla kullanıcı bu tarihler arasında mesaiye kalmaktadır.")

    def create(self, validated_data):
        request = self.context["request"]
        requester = request.user

        entries_data = validated_data.pop("entries")
        start_at = validated_data["start_at"]
        end_at = validated_data["end_at"]

        # Snapshot team from profile if available
        team = getattr(getattr(requester, "profile", None), "team", "") or ""

        # Validate overlaps before creating
        users = [row["user"] for row in entries_data]
        self._validate_overlaps(requester=requester, start_at=start_at, end_at=end_at, entries_users=users)

        ot = OvertimeRequest.objects.create(requester=requester, team=team, **validated_data)
        OvertimeEntry.objects.bulk_create([
            OvertimeEntry(request=ot, user=row["user"], job_no=row["job_no"], description=row.get("description", ""))
            for row in entries_data
        ])

        # Fire approval hook (no-op for now)
        ot.send_for_approval()

        return ot


class OvertimeRequestUpdateSerializer(serializers.ModelSerializer):
    """
    Allow requester to update reason while 'submitted'.
    (Editing time range or entries is typically disallowed after submission;
     if you want edits, you can expand here with extra checks.)
    """
    class Meta:
        model = OvertimeRequest
        fields = ["reason"]

    def validate(self, attrs):
        obj: OvertimeRequest = self.instance
        if obj.status != "submitted":
            raise serializers.ValidationError("Only 'submitted' requests can be edited.")
        return attrs


class OvertimeEntryShortSerializer(serializers.ModelSerializer):
    request_start_at = serializers.DateTimeField(source="request.start_at", read_only=True)
    request_end_at   = serializers.DateTimeField(source="request.end_at",   read_only=True)
    class Meta:
        model = OvertimeEntry
        fields = ["id", "job_no", "description", "approved_hours", "request_start_at", "request_end_at"]

class UserOvertimeListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    team = serializers.CharField(source="profile.team", read_only=True)
    team_label = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username
    
    def get_team_label(self, obj):
        return TEAM_LABELS.get(obj.profile.team, obj.profile.team or "")
    
    def get_entries(self, obj):
        # We’ll prefetch filtered entries into obj.entries_for_day
        entries = getattr(obj, "entries_for_day", None)
        if entries is None:
            # Fallback (shouldn’t happen if view uses Prefetch)
            from overtime.models import OvertimeEntry
            start_of_day = self.context["start_of_day"]
            end_exclusive = self.context["end_exclusive"]
            entries = OvertimeEntry.objects.filter(
                user=obj,
                request__status="approved",
                request__start_at__lt=end_exclusive,
                request__end_at__gte=start_of_day,
            )
        return OvertimeEntryShortSerializer(entries, many=True).data

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "team", "team_label", "entries"]