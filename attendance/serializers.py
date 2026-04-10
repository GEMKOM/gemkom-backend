from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSite, ShiftRule

User = get_user_model()


class AttendanceRecordSerializer(serializers.ModelSerializer):
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'status',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours',
            'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'method', 'status',
            'client_ip',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours',
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
    """Payload for POST /attendance/check-out/ — no required fields for now."""
    pass


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

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'check_in_time', 'check_out_time',
            'method', 'status',
            'check_in_lat', 'check_in_lon',
            'check_out_lat', 'check_out_lon',
            'client_ip',
            'override_reason',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'overtime_hours',
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


class HRAttendanceCreateSerializer(serializers.ModelSerializer):
    """HR manual entry — creates a complete record directly."""

    class Meta:
        model = AttendanceRecord
        fields = ['user', 'date', 'check_in_time', 'check_out_time', 'notes']

    def validate(self, data):
        if data.get('check_out_time') and data['check_out_time'] <= data['check_in_time']:
            raise serializers.ValidationError("check_out_time must be after check_in_time.")
        return data


# ---------------------------------------------------------------------------
# Site & ShiftRule serializers
# ---------------------------------------------------------------------------

class AttendanceSiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceSite
        fields = ['id', 'name', 'latitude', 'longitude', 'radius_meters', 'allowed_ip_ranges']


class ShiftRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftRule
        fields = ['id', 'name', 'work_location', 'expected_start', 'expected_end',
                  'overtime_threshold_minutes', 'is_active']
