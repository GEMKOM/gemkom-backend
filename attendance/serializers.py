from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AttendanceLeaveInterval, AttendanceRecord, AttendanceSite, ShiftRule

User = get_user_model()


class AttendanceLeaveIntervalSerializer(serializers.ModelSerializer):
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)

    class Meta:
        model = AttendanceLeaveInterval
        fields = ['id', 'start_time', 'end_time', 'leave_type', 'leave_type_display', 'notes', 'created_at']
        read_only_fields = ['id', 'leave_type_display', 'created_at']


class AttendanceRecordSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    is_paid_leave = serializers.BooleanField(read_only=True)
    leave_intervals = AttendanceLeaveIntervalSerializer(many=True, read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'leave_type', 'leave_type_display', 'is_paid_leave',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'notes',
            'leave_intervals',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'method', 'method_display', 'status', 'status_display',
            'leave_type_display', 'is_paid_leave',
            'client_ip',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'leave_intervals',
            'created_at', 'updated_at',
        ]

    def get_user_display(self, obj):
        u = obj.user
        return u.get_full_name() or u.username

    def get_reviewed_by_display(self, obj):
        if not obj.reviewed_by:
            return None
        u = obj.reviewed_by
        return u.get_full_name() or u.username


class CheckInSerializer(serializers.Serializer):
    """
    Payload for POST /attendance/check-in/
    For white-collar IP check-in: send with no extra fields.
    override_reason signals a manual override request.
    """
    override_reason = serializers.CharField(required=False, allow_blank=True, default='')


class CheckOutSerializer(serializers.Serializer):
    """
    Payload for POST /attendance/check-out/
    override_reason signals a manual override request when IP check fails.
    """
    override_reason = serializers.CharField(required=False, allow_blank=True, default='')


# ---------------------------------------------------------------------------
# HR serializers
# ---------------------------------------------------------------------------

class HRAttendanceRecordSerializer(serializers.ModelSerializer):
    """
    HR can read all fields and edit: check_in_time, check_out_time, notes, status.
    Used for HR manual entry and editing.
    """
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    is_paid_leave = serializers.BooleanField(read_only=True)
    leave_intervals = AttendanceLeaveIntervalSerializer(many=True, read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'leave_type', 'leave_type_display', 'is_paid_leave',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'notes',
            'leave_intervals',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_display', 'reviewed_by_display', 'client_ip', 'leave_intervals', 'created_at', 'updated_at']

    def get_user_display(self, obj):
        u = obj.user
        return u.get_full_name() or u.username

    def get_reviewed_by_display(self, obj):
        if not obj.reviewed_by:
            return None
        u = obj.reviewed_by
        return u.get_full_name() or u.username

    def update(self, instance, validated_data):
        from attendance.services import compute_overtime_minutes, compute_shift_compliance
        # If HR didn't explicitly send a method, stamp it as hr_manual
        if 'method' not in validated_data:
            validated_data['method'] = AttendanceRecord.METHOD_HR
        instance = super().update(instance, validated_data)
        update_fields = []
        # Recompute whenever both times are present and either was changed
        time_fields = {'check_in_time', 'check_out_time'}
        if time_fields & set(validated_data.keys()) and instance.check_in_time and instance.check_out_time:
            instance.overtime_minutes = compute_overtime_minutes(instance.user, instance.check_in_time, instance.check_out_time)
            instance.late_minutes, instance.early_leave_minutes = compute_shift_compliance(instance.user, instance.check_in_time, instance.check_out_time)
            update_fields += ['overtime_minutes', 'late_minutes', 'early_leave_minutes']
            instance.save(update_fields=update_fields)
        return instance


class HRAttendanceCreateSerializer(serializers.ModelSerializer):
    """
    HR manual entry — creates a complete attendance or leave record.

    For normal attendance: provide check_in_time and check_out_time.
    For leave: provide leave_type only — no times needed.
    """

    class Meta:
        model = AttendanceRecord
        fields = ['user', 'date', 'check_in_time', 'check_out_time', 'leave_type', 'notes']
        extra_kwargs = {
            'check_in_time': {'required': False},
            'check_out_time': {'required': False},
        }

    def validate(self, data):
        leave_type = data.get('leave_type')
        check_in = data.get('check_in_time')
        check_out = data.get('check_out_time')

        if leave_type:
            # Leave record — times must not be provided
            if check_in or check_out:
                raise serializers.ValidationError(
                    "check_in_time and check_out_time must not be set for leave records."
                )
        else:
            # Normal attendance — check_in_time is required
            if not check_in:
                raise serializers.ValidationError("check_in_time is required for attendance records.")
            if check_out and check_out <= check_in:
                raise serializers.ValidationError("check_out_time must be after check_in_time.")

        return data

    def create(self, validated_data):
        from attendance.services import compute_overtime_minutes, compute_shift_compliance
        leave_type = validated_data.get('leave_type')

        if leave_type:
            validated_data['status'] = AttendanceRecord.STATUS_LEAVE
            validated_data['method'] = AttendanceRecord.METHOD_HR

        obj = super().create(validated_data)

        if obj.check_in_time and obj.check_out_time:
            obj.overtime_minutes = compute_overtime_minutes(obj.user, obj.check_in_time, obj.check_out_time)
            obj.late_minutes, obj.early_leave_minutes = compute_shift_compliance(obj.user, obj.check_in_time, obj.check_out_time)
            obj.save(update_fields=['overtime_minutes', 'late_minutes', 'early_leave_minutes'])
        return obj


# ---------------------------------------------------------------------------
# Site & ShiftRule serializers
# ---------------------------------------------------------------------------

class AttendanceSiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceSite
        fields = ['id', 'name', 'latitude', 'longitude', 'radius_meters', 'allowed_ip_ranges']


class ShiftRuleSerializer(serializers.ModelSerializer):
    assigned_user_count = serializers.SerializerMethodField()

    class Meta:
        model = ShiftRule
        fields = ['id', 'name', 'expected_start', 'expected_end',
                  'overtime_threshold_minutes', 'is_active', 'is_default', 'assigned_user_count']

    def get_assigned_user_count(self, obj):
        return obj.assigned_users.count()


class UserShiftRuleAssignSerializer(serializers.Serializer):
    """Assign or unassign a shift rule for a user. Pass shift_rule_id=null to clear."""
    user_id = serializers.IntegerField()
    shift_rule_id = serializers.IntegerField(allow_null=True)


class HRLeaveIntervalCreateSerializer(serializers.ModelSerializer):
    """
    HR creates or edits a partial-day leave interval on an existing AttendanceRecord.
    `record` is set from the URL, not the request body.
    """
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)

    class Meta:
        model = AttendanceLeaveInterval
        fields = ['id', 'start_time', 'end_time', 'leave_type', 'leave_type_display', 'notes', 'created_at']
        read_only_fields = ['id', 'leave_type_display', 'created_at']

    def validate(self, data):
        start = data.get('start_time', getattr(self.instance, 'start_time', None))
        end = data.get('end_time', getattr(self.instance, 'end_time', None))

        if start and end and end <= start:
            raise serializers.ValidationError("end_time must be after start_time.")

        # Validate interval does not overlap with the work session [check_in, check_out]
        record = self.context.get('record') or getattr(self.instance, 'record', None)
        if record and start and end:
            check_in = record.check_in_time
            check_out = record.check_out_time
            if check_in and check_out:
                # Overlap exists if interval starts before check_out AND ends after check_in
                if start < check_out and end > check_in:
                    raise serializers.ValidationError(
                        "Leave interval cannot overlap with the work session "
                        f"({check_in:%H:%M}–{check_out:%H:%M}). "
                        "It must end before check-in or start after check-out."
                    )
            elif check_in and end > check_in:
                # No check_out yet — interval must not start during/before the ongoing session
                raise serializers.ValidationError(
                    "Leave interval cannot overlap with the ongoing work session "
                    f"(checked in at {check_in:%H:%M})."
                )

        return data
