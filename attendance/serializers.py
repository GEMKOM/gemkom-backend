from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import AttendanceLeaveInterval, AttendanceRecord, AttendanceSession, AttendanceSite, ShiftRule

_ISTANBUL = ZoneInfo(settings.APP_DEFAULT_TZ)

User = get_user_model()


class IstanbulDateTimeField(serializers.DateTimeField):
    """
    Interprets naive datetime strings sent by HR as Europe/Istanbul local time
    and converts them to UTC-aware datetimes before saving.
    """
    def to_internal_value(self, value):
        if isinstance(value, str) and value and not any(c in value for c in ('+', 'Z')) and 'T' in value:
            from datetime import datetime as _dt
            try:
                naive = _dt.fromisoformat(value)
                value = naive.replace(tzinfo=_ISTANBUL).isoformat()
            except ValueError:
                pass
        return super().to_internal_value(value)


# ---------------------------------------------------------------------------
# Session serializers
# ---------------------------------------------------------------------------

class AttendanceSessionSerializer(serializers.ModelSerializer):
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'check_in_lat', 'check_in_lon', 'check_out_lat', 'check_out_lon',
            'client_ip', 'override_reason',
            'duration_minutes',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class HRSessionSerializer(serializers.ModelSerializer):
    """
    HR can create or edit sessions directly.
    `record` is set from the URL context, not the request body.
    """
    method_display = serializers.CharField(source='get_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration_minutes = serializers.IntegerField(read_only=True)
    check_in_time = IstanbulDateTimeField()
    check_out_time = IstanbulDateTimeField(required=False, allow_null=True)

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'check_in_time', 'check_out_time',
            'method', 'method_display', 'status', 'status_display',
            'check_in_lat', 'check_in_lon', 'check_out_lat', 'check_out_lon',
            'client_ip', 'override_reason',
            'duration_minutes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'method_display', 'status_display', 'duration_minutes', 'created_at', 'updated_at']

    def validate(self, data):
        check_in = data.get('check_in_time', getattr(self.instance, 'check_in_time', None))
        check_out = data.get('check_out_time', getattr(self.instance, 'check_out_time', None))
        if check_in and check_out and check_out <= check_in:
            raise serializers.ValidationError("check_out_time must be after check_in_time.")
        return data


# ---------------------------------------------------------------------------
# Leave interval serializers
# ---------------------------------------------------------------------------

class AttendanceLeaveIntervalSerializer(serializers.ModelSerializer):
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)

    class Meta:
        model = AttendanceLeaveInterval
        fields = ['id', 'start_time', 'end_time', 'leave_type', 'leave_type_display', 'notes', 'created_at']
        read_only_fields = ['id', 'leave_type_display', 'created_at']


# ---------------------------------------------------------------------------
# AttendanceRecord serializers
# ---------------------------------------------------------------------------

class AttendanceRecordSerializer(serializers.ModelSerializer):
    """Employee-facing read-only record serializer. Includes nested sessions."""
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    is_paid_leave = serializers.BooleanField(read_only=True)
    sessions = AttendanceSessionSerializer(many=True, read_only=True)
    leave_intervals = AttendanceLeaveIntervalSerializer(many=True, read_only=True)
    first_check_in = serializers.DateTimeField(read_only=True)
    last_check_out = serializers.DateTimeField(read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'status', 'status_display',
            'leave_type', 'leave_type_display', 'is_paid_leave',
            'first_check_in', 'last_check_out',
            'total_present_minutes',
            'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'notes',
            'sessions',
            'leave_intervals',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_user_display(self, obj):
        u = obj.user
        return u.get_full_name() or u.username

    def get_reviewed_by_display(self, obj):
        if not obj.reviewed_by:
            return None
        u = obj.reviewed_by
        return u.get_full_name() or u.username


class HRAttendanceRecordSerializer(serializers.ModelSerializer):
    """HR read + partial-edit serializer."""
    user_display = serializers.SerializerMethodField()
    reviewed_by_display = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    is_paid_leave = serializers.BooleanField(read_only=True)
    sessions = AttendanceSessionSerializer(many=True, read_only=True)
    leave_intervals = AttendanceLeaveIntervalSerializer(many=True, read_only=True)
    first_check_in = serializers.DateTimeField(read_only=True)
    last_check_out = serializers.DateTimeField(read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'user', 'user_display', 'date',
            'status', 'status_display',
            'leave_type', 'leave_type_display', 'is_paid_leave',
            'first_check_in', 'last_check_out',
            'total_present_minutes',
            'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'reviewed_by', 'reviewed_by_display', 'reviewed_at',
            'notes',
            'sessions',
            'leave_intervals',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user_display', 'reviewed_by_display', 'status_display',
            'leave_type_display', 'is_paid_leave',
            'first_check_in', 'last_check_out',
            'total_present_minutes', 'overtime_minutes', 'late_minutes', 'early_leave_minutes',
            'sessions', 'leave_intervals',
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


class HRAttendanceCreateSerializer(serializers.ModelSerializer):
    """
    HR manual entry — creates a full-day attendance or leave record.

    For normal attendance: leave check_in/out to HR session creation via
    HRSessionListCreateView after record creation, OR provide sessions inline.
    For leave: provide leave_type only.
    """
    class Meta:
        model = AttendanceRecord
        fields = ['user', 'date', 'leave_type', 'notes']
        extra_kwargs = {
            'leave_type': {'required': False},
            'notes': {'required': False},
        }

    def validate(self, data):
        leave_type = data.get('leave_type')
        if not leave_type:
            # Non-leave records just need user + date; sessions added separately
            if not data.get('user') or not data.get('date'):
                raise serializers.ValidationError("user and date are required.")
        return data

    def create(self, validated_data):
        leave_type = validated_data.get('leave_type')
        if leave_type:
            validated_data['status'] = AttendanceRecord.STATUS_LEAVE
        else:
            validated_data.setdefault('status', AttendanceRecord.STATUS_COMPLETE)
        validated_data['method'] = AttendanceRecord.METHOD_HR if hasattr(AttendanceRecord, 'METHOD_HR') else 'hr_manual'
        # method no longer lives on AttendanceRecord — drop it silently
        validated_data.pop('method', None)
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# HR summary serializer — one row per user, aggregated across a date range
# ---------------------------------------------------------------------------

class HRAttendanceSummarySerializer(serializers.Serializer):
    """
    Read-only. Each instance is a plain dict produced by HRAttendanceSummaryView.
    One row per user covering the queried date range.
    """
    user_id = serializers.IntegerField()
    user_display = serializers.CharField()
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    # Days breakdown
    total_working_days = serializers.IntegerField(
        help_text="Weekdays minus public holidays in the range."
    )
    days_present = serializers.IntegerField(
        help_text="Days the user has an active/complete/pending record."
    )
    days_leave = serializers.IntegerField(
        help_text="Days the user has a leave record."
    )
    days_absent = serializers.IntegerField(
        help_text="Past working days with no record or a rejected record."
    )

    # Time aggregates (minutes)
    total_present_minutes = serializers.IntegerField()
    total_expected_minutes = serializers.IntegerField(
        help_text="Expected work minutes for the range: working_days × shift_length."
    )
    total_overtime_minutes = serializers.IntegerField()
    total_late_minutes = serializers.IntegerField()
    total_early_leave_minutes = serializers.IntegerField()

    # Session count across all records in range
    session_count = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Check-in / check-out request serializers
# ---------------------------------------------------------------------------

class CheckInSerializer(serializers.Serializer):
    override_reason = serializers.CharField(required=False, allow_blank=True, default='')


class CheckOutSerializer(serializers.Serializer):
    override_reason = serializers.CharField(required=False, allow_blank=True, default='')


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
        fields = [
            'id', 'name', 'expected_start', 'expected_end',
            'overtime_threshold_minutes', 'is_active', 'is_default', 'assigned_user_count',
        ]

    def get_assigned_user_count(self, obj):
        return obj.assigned_users.count()


class UserShiftRuleAssignSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    shift_rule_id = serializers.IntegerField(allow_null=True)


# ---------------------------------------------------------------------------
# Leave interval HR serializer (with session-aware validation)
# ---------------------------------------------------------------------------

class HRLeaveIntervalCreateSerializer(serializers.ModelSerializer):
    """
    HR creates or edits a partial-day leave interval on an existing AttendanceRecord.
    Validates that the interval does not overlap with any session on the record.
    """
    leave_type_display = serializers.CharField(source='get_leave_type_display', read_only=True)
    start_time = IstanbulDateTimeField()
    end_time = IstanbulDateTimeField()

    class Meta:
        model = AttendanceLeaveInterval
        fields = ['id', 'start_time', 'end_time', 'leave_type', 'leave_type_display', 'notes', 'created_at']
        read_only_fields = ['id', 'leave_type_display', 'created_at']

    def validate(self, data):
        start = data.get('start_time', getattr(self.instance, 'start_time', None))
        end = data.get('end_time', getattr(self.instance, 'end_time', None))

        if start and end and end <= start:
            raise serializers.ValidationError("end_time must be after start_time.")

        record = self.context.get('record') or getattr(self.instance, 'record', None)
        if record and start and end:
            for session in record.sessions.filter(check_in_time__isnull=False):
                s_in = session.check_in_time
                s_out = session.check_out_time
                if s_out:
                    # Closed session: interval must not overlap [s_in, s_out]
                    if start < s_out and end > s_in:
                        raise serializers.ValidationError(
                            f"Leave interval overlaps with a work session "
                            f"({s_in:%H:%M}–{s_out:%H:%M}). "
                            "It must fall entirely outside all work sessions."
                        )
                else:
                    # Open session: interval must not start during the ongoing session
                    if end > s_in:
                        raise serializers.ValidationError(
                            f"Leave interval cannot overlap with the ongoing work session "
                            f"(checked in at {s_in:%H:%M})."
                        )

        return data
