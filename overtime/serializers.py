# overtime/serializers.py
from django.contrib.contenttypes.models import ContentType
from approvals.models import ApprovalWorkflow
from approvals.serializers import WorkflowSerializer
from rest_framework import serializers
from django.contrib.auth import get_user_model

from users.helpers import get_dept_code_for_user, GROUP_TO_TEAM, TEAM_LABELS

from tasks.models import Operation

from .models import OvertimeRequest, OvertimeEntry

User = get_user_model()


def raise_if_overtime_clash(*, start_at, end_at, users, exclude_pk=None):
    """
    Reject the request when any of ``users`` is already booked on an overlapping
    open/approved overtime request.

    Rejected entries do **not** count. Someone retracted from a request during
    partial approval is not working that overtime, so the slot is free and they
    must be bookable again — otherwise rejecting a person permanently blocks
    them for that time range.

    Queried against OvertimeEntry rather than OvertimeRequest so the user and
    status conditions provably apply to the *same* entry row; filtering a
    multi-valued relation from the request side makes that easy to get wrong.
    """
    qs = (
        OvertimeEntry.objects
        .filter(
            user__in=users,
            request__status__in=["submitted", "approved"],
            # overlap: existing.start < new.end AND existing.end > new.start
            request__start_at__lt=end_at,
            request__end_at__gt=start_at,
        )
        .exclude(status="rejected")
        .select_related("user")
    )
    if exclude_pk is not None:
        qs = qs.exclude(request_id=exclude_pk)

    clashes: dict = {}
    for entry in qs:
        name = entry.user.get_full_name() or entry.user.username
        clashes.setdefault(name, set()).add(entry.request_id)
    if not clashes:
        return

    detail = "; ".join(
        f"{name} (#{', #'.join(str(r) for r in sorted(ids))})"
        for name, ids in sorted(clashes.items())
    )
    raise serializers.ValidationError(
        f"Bu tarih aralığında zaten mesaide olan kullanıcılar: {detail}."
    )


def _create_entries_with_operations(ot, entries_data):
    """
    Create OvertimeEntry rows for a request and attach their machining operations.
    Operations whose part.job_no does not match the entry's job_no are dropped
    (defensive — the UI already scopes the picker to the entry's job).
    """
    for row in entries_data:
        operations = row.get("operations") or []
        entry = OvertimeEntry.objects.create(
            request=ot,
            user=row["user"],
            job_no=row["job_no"],
            description=row.get("description", ""),
        )
        if operations:
            job_no = (row["job_no"] or "").strip()
            valid_ops = [op for op in operations if (op.part.job_no or "").strip() == job_no] if job_no else list(operations)
            if valid_ops:
                entry.operations.set(valid_ops)


class OvertimeEntryOperationSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    job_no = serializers.CharField(source="part.job_no", read_only=True)

    class Meta:
        model = Operation
        fields = ["key", "name", "order", "part_id", "part_name", "job_no"]


class OvertimeEntryReadSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    user_full_name = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    operations = OvertimeEntryOperationSerializer(many=True, read_only=True)

    class Meta:
        model = OvertimeEntry
        fields = [
            "id", "user_id", "user_username", "user_full_name", "job_no", "description",
            "approved_hours", "status", "status_label", "operations", "created_at",
        ]

    def get_user_full_name(self, obj):
        return getattr(obj.user, "get_full_name", lambda: "")() or obj.user.username

    def get_status_label(self, obj):
        return obj.get_status_display()


class OvertimeEntryWriteSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    operations = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Operation.objects.all(), required=False
    )

    class Meta:
        model = OvertimeEntry
        fields = ["user", "job_no", "description", "operations"]


class OvertimeRequestListSerializer(serializers.ModelSerializer):
    requester_username = serializers.CharField(source="requester.username", read_only=True)
    total_users = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    def get_total_users(self, obj):
        # Count participants excluding entries rejected during partial approval.
        # Uses the prefetched `entries` (no extra query). Pending (historical)
        # and approved both count; only rejected are dropped.
        return sum(1 for e in obj.entries.all() if e.status != "rejected")
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
        raise_if_overtime_clash(
            start_at=start_at, end_at=end_at, users=entries_users,
            exclude_pk=instance.pk if instance else None,
        )

    def create(self, validated_data):
        request = self.context["request"]
        requester = request.user

        entries_data = validated_data.pop("entries")
        start_at = validated_data["start_at"]
        end_at = validated_data["end_at"]

        # Snapshot team from group membership
        team = get_dept_code_for_user(requester) or ""

        # Validate overlaps before creating
        users = [row["user"] for row in entries_data]
        self._validate_overlaps(requester=requester, start_at=start_at, end_at=end_at, entries_users=users)

        ot = OvertimeRequest.objects.create(requester=requester, team=team, **validated_data)
        _create_entries_with_operations(ot, entries_data)

        # Fire approval hook
        ot.send_for_approval()

        return ot


class OvertimeRequestUpdateSerializer(serializers.ModelSerializer):
    """
    - While 'submitted': requester may only edit the reason.
    - While 'rejected' or 'cancelled': requester may edit the full request
      (times, reason, entries) and it is re-submitted for approval on the same
      record (a fresh approval workflow is created).
    """
    entries = OvertimeEntryWriteSerializer(many=True, required=False)

    class Meta:
        model = OvertimeRequest
        fields = ["reason", "start_at", "end_at", "entries"]

    def validate(self, attrs):
        obj: OvertimeRequest = self.instance
        request = self.context.get("request")
        if request is not None:
            u = request.user
            if obj.requester_id != u.id and not (u.is_staff or u.is_superuser):
                raise serializers.ValidationError("Yalnızca talebi oluşturan kişi düzenleyebilir.")
        if obj.status == "submitted":
            # Reason-only edit; ignore any other supplied fields.
            return {"reason": attrs.get("reason", obj.reason)}

        if obj.status not in ("rejected", "cancelled"):
            raise serializers.ValidationError(
                "Yalnızca 'Onay Bekliyor', 'Reddedildi' veya 'İptal Edildi' talepler düzenlenebilir."
            )

        start_at = attrs.get("start_at", obj.start_at)
        end_at = attrs.get("end_at", obj.end_at)
        if end_at <= start_at:
            raise serializers.ValidationError("Bitiş zamanı başlangıçtan sonra olmalı.")
        attrs["start_at"] = start_at
        attrs["end_at"] = end_at
        return attrs

    def _validate_overlaps(self, *, start_at, end_at, entries_users, instance):
        raise_if_overtime_clash(
            start_at=start_at, end_at=end_at, users=entries_users,
            exclude_pk=instance.pk,
        )

    def update(self, instance, validated_data):
        # Simple reason-only path for still-open requests.
        if instance.status == "submitted":
            instance.reason = validated_data.get("reason", instance.reason)
            instance.save(update_fields=["reason", "updated_at"])
            return instance

        # Resubmit path (rejected/cancelled) — reopen the same record.
        entries_data = validated_data.pop("entries", None)
        instance.start_at = validated_data.get("start_at", instance.start_at)
        instance.end_at = validated_data.get("end_at", instance.end_at)
        instance.reason = validated_data.get("reason", instance.reason)

        if entries_data is not None:
            users = [row["user"] for row in entries_data]
            self._validate_overlaps(
                start_at=instance.start_at, end_at=instance.end_at,
                entries_users=users, instance=instance,
            )
            instance.entries.all().delete()

        instance.status = "submitted"
        instance.resubmit_count = (instance.resubmit_count or 0) + 1
        instance.save(update_fields=["start_at", "end_at", "reason", "status", "resubmit_count", "updated_at"])

        if entries_data is not None:
            _create_entries_with_operations(instance, entries_data)

        # Start a fresh approval workflow on the reopened request.
        instance.send_for_approval()
        return instance


class OvertimeEntryShortSerializer(serializers.ModelSerializer):
    request_start_at = serializers.DateTimeField(source="request.start_at", read_only=True)
    request_end_at   = serializers.DateTimeField(source="request.end_at",   read_only=True)
    class Meta:
        model = OvertimeEntry
        fields = ["id", "job_no", "description", "approved_hours", "request_start_at", "request_end_at"]

class UserOvertimeListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    team = serializers.SerializerMethodField()
    team_label = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_team(self, obj):
        return get_dept_code_for_user(obj)

    def get_team_label(self, obj):
        team = get_dept_code_for_user(obj)
        return TEAM_LABELS.get(team, "") if team else ""
    
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
            ).exclude(status="rejected")
        return OvertimeEntryShortSerializer(entries, many=True).data

    class Meta:
        model = User
        fields = ["id", "username", "full_name", "team", "team_label", "entries"]