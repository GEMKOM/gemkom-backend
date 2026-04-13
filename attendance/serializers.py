from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSite, ShiftRule

User = get_user_model()


class AttendanceRecordSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours', 'late_minutes', 'early_leave_minutes',
            'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'method', 'method_display', 'status', 'status_display',
            'client_ip',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours', 'late_minutes', 'early_leave_minutes',
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

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours', 'late_minutes', 'early_leave_minutes',
            'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'user_display', 'reviewed_by_display', 'client_ip', 'created_at', 'updated_at']

    def get_user_display(self, obj):
        u = obj.user
        return u.get_full_name() or u.username

    def get_reviewed_by_display(self, obj):
        if not obj.reviewed_by:
            return None
        u = obj.reviewed_by
        return u.get_full_name() or u.username

    def update(self, instance, validated_data):
        from attendance.services import compute_overtime_hours, compute_shift_compliance
        instance = super().update(instance, validated_data)
        # Recompute whenever both times are present and either was changed
        time_fields = {'check_in_time', 'check_out_time'}
        if time_fields & set(validated_data.keys()) and instance.check_in_time and instance.check_out_time:
            instance.overtime_hours = compute_overtime_hours(instance.user, instance.check_in_time, instance.check_out_time)
            instance.late_minutes, instance.early_leave_minutes = compute_shift_compliance(instance.user, instance.check_in_time, instance.check_out_time)
            instance.save(update_fields=['overtime_hours', 'late_minutes', 'early_leave_minutes'])
        return instance


class HRAttendanceCreateSerializer(serializers.ModelSerializer):
    """HR manual entry — creates a complete record directly."""

    class Meta:
        model = AttendanceRecord
        fields = ['user', 'date', 'check_in_time', 'check_out_time', 'notes']

    def validate(self, data):
        if data.get('check_out_time') and data['check_out_time'] <= data['check_in_time']:
            raise serializers.ValidationError("check_out_time must be after check_in_time.")
        return data

    def create(self, validated_data):
        from attendance.services import compute_overtime_hours, compute_shift_compliance
        obj = super().create(validated_data)
        if obj.check_out_time:
            obj.overtime_hours = compute_overtime_hours(obj.user, obj.check_in_time, obj.check_out_time)
            obj.late_minutes, obj.early_leave_minutes = compute_shift_compliance(obj.user, obj.check_in_time, obj.check_out_time)
            obj.save(update_fields=['overtime_hours', 'late_minutes', 'early_leave_minutes'])
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
