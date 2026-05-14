"""
Attendance service layer.

Responsibilities:
- Extract and validate client IP against AttendanceSite.allowed_ip_ranges
- Compute overtime / shift compliance from a day's sessions
- Create check-in sessions and get-or-create the daily AttendanceRecord
- Recompute daily aggregates on the AttendanceRecord after each session change
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IP helpers
# ---------------------------------------------------------------------------

def get_client_ip(request) -> str | None:
    """
    Extract the real client IP from the request.
    Respects X-Forwarded-For as set by Cloud Run / load balancers.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def ip_in_allowed_ranges(ip: str, allowed_ranges: list[str]) -> bool:
    """Return True if `ip` falls within any of the CIDR ranges in `allowed_ranges`."""
    if not ip or not allowed_ranges:
        return False
    try:
        client = ipaddress.ip_address(ip)
    except ValueError:
        logger.warning("attendance: could not parse client IP %r", ip)
        return False

    for cidr in allowed_ranges:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if client in network:
                return True
        except ValueError:
            logger.warning("attendance: invalid CIDR range %r in AttendanceSite config", cidr)
    return False


# ---------------------------------------------------------------------------
# Site config helper
# ---------------------------------------------------------------------------

def get_active_site():
    """Return the first AttendanceSite row, or None if not configured yet."""
    from attendance.models import AttendanceSite
    return AttendanceSite.objects.first()


# ---------------------------------------------------------------------------
# Shift rule helper
# ---------------------------------------------------------------------------

def _get_shift_rule(user):
    """Return the applicable ShiftRule for a user, or None."""
    from attendance.models import ShiftRule
    profile = getattr(user, 'profile', None)
    rule = getattr(profile, 'shift_rule', None)
    if rule is None or not rule.is_active:
        rule = ShiftRule.objects.filter(is_active=True, is_default=True).first()
    return rule


# ---------------------------------------------------------------------------
# IP check-in gate
# ---------------------------------------------------------------------------

def attempt_ip_checkin(request, user) -> tuple[bool, str | None]:
    """
    Try to authenticate via office IP.

    Returns (success: bool, failure_reason: str | None).
    failure_reason is None on success; one of:
      'site_not_configured' | 'no_ip_ranges_configured' | 'not_on_office_network'
    """
    site = get_active_site()
    if site is None:
        return False, 'site_not_configured'
    if not site.allowed_ip_ranges:
        return False, 'no_ip_ranges_configured'
    client_ip = get_client_ip(request)
    if ip_in_allowed_ranges(client_ip, site.allowed_ip_ranges):
        return True, None
    return False, 'not_on_office_network'


# ---------------------------------------------------------------------------
# Daily record + session creation
# ---------------------------------------------------------------------------

def get_or_create_record(user, day: date) -> 'AttendanceRecord':
    """
    Return (or create) the AttendanceRecord for user+day.
    New records are created with status=active; the caller sets the real status.
    """
    from attendance.models import AttendanceRecord
    record, _ = AttendanceRecord.objects.get_or_create(
        user=user,
        date=day,
        defaults={'status': AttendanceRecord.STATUS_ACTIVE},
    )
    return record


def create_session(
    record: 'AttendanceRecord',
    method: str,
    client_ip: str | None = None,
    override_reason: str = '',
) -> 'AttendanceSession':
    """
    Create and return a new AttendanceSession on `record`.
    Sessions created via manual_override start as pending; others start open.
    """
    from attendance.models import AttendanceSession

    session_status = (
        AttendanceSession.STATUS_PENDING
        if method == AttendanceSession.METHOD_OVERRIDE
        else AttendanceSession.STATUS_OPEN
    )

    return AttendanceSession.objects.create(
        record=record,
        check_in_time=timezone.now(),
        method=method,
        status=session_status,
        client_ip=client_ip,
        override_reason=override_reason,
    )


# ---------------------------------------------------------------------------
# Aggregate computation
# ---------------------------------------------------------------------------

def compute_overtime_minutes(
    user,
    check_in: datetime,
    check_out: datetime,
) -> int:
    """
    Determine overtime minutes for a single work window.
    Used for the legacy single-session path and HR override approval.
    """
    rule = _get_shift_rule(user)
    if rule is None:
        return 0

    tz = ZoneInfo(settings.APP_DEFAULT_TZ)
    local_check_in = check_in.astimezone(tz)
    expected_end_dt = datetime.combine(local_check_in.date(), rule.expected_end).replace(tzinfo=tz)

    threshold = timedelta(minutes=rule.overtime_threshold_minutes)
    overtime_delta = check_out - expected_end_dt

    if overtime_delta > threshold:
        return int(overtime_delta.total_seconds() // 60)
    return 0


def compute_shift_compliance(
    user,
    check_in: datetime,
    check_out: datetime,
    leave_intervals: list[tuple[datetime, datetime]] | None = None,
) -> tuple[int, int]:
    """
    Compute (late_minutes, early_leave_minutes) for a single work window.
    Approved leave intervals that overlap the penalty windows are subtracted.
    """
    rule = _get_shift_rule(user)
    if rule is None:
        return 0, 0

    tz = ZoneInfo(settings.APP_DEFAULT_TZ)
    local_check_in = check_in.astimezone(tz)
    day = local_check_in.date()

    expected_start_dt = datetime.combine(day, rule.expected_start).replace(tzinfo=tz)
    expected_end_dt = datetime.combine(day, rule.expected_end).replace(tzinfo=tz)

    late_delta = check_in - expected_start_dt
    late_minutes = max(0, int(late_delta.total_seconds() // 60))

    early_delta = expected_end_dt - check_out
    early_leave_minutes = max(0, int(early_delta.total_seconds() // 60))

    if leave_intervals:
        for iv_start, iv_end in leave_intervals:
            if late_minutes > 0:
                overlap_start = max(iv_start, expected_start_dt)
                overlap_end = min(iv_end, check_in)
                if overlap_end > overlap_start:
                    covered = int((overlap_end - overlap_start).total_seconds() // 60)
                    late_minutes = max(0, late_minutes - covered)

            if early_leave_minutes > 0:
                overlap_start = max(iv_start, check_out)
                overlap_end = min(iv_end, expected_end_dt)
                if overlap_end > overlap_start:
                    covered = int((overlap_end - overlap_start).total_seconds() // 60)
                    early_leave_minutes = max(0, early_leave_minutes - covered)

    return late_minutes, early_leave_minutes


def recompute_record_aggregates(record) -> None:
    """
    Recompute all daily aggregate fields on an AttendanceRecord from its sessions.

    - total_present_minutes: sum of closed session durations
    - late_minutes: first session start vs expected_start (with leave interval offsets)
    - early_leave_minutes: last closed session end vs expected_end (with offsets)
    - overtime_minutes: total work minutes beyond expected_end

    Saves only the aggregate fields; does not touch status.
    """
    from attendance.models import AttendanceSession

    closed_sessions = list(
        record.sessions
        .filter(status=AttendanceSession.STATUS_CLOSED)
        .order_by('check_in_time')
    )

    # Total present
    total_present = sum(
        max(0, int((s.check_out_time - s.check_in_time).total_seconds() // 60))
        for s in closed_sessions
        if s.check_out_time
    )

    if not closed_sessions:
        record.total_present_minutes = 0
        record.late_minutes = 0
        record.early_leave_minutes = 0
        record.overtime_minutes = 0
        record.save(update_fields=[
            'total_present_minutes', 'late_minutes',
            'early_leave_minutes', 'overtime_minutes', 'updated_at',
        ])
        return

    rule = _get_shift_rule(record.user)
    if rule is None:
        record.total_present_minutes = total_present
        record.late_minutes = 0
        record.early_leave_minutes = 0
        record.overtime_minutes = 0
        record.save(update_fields=[
            'total_present_minutes', 'late_minutes',
            'early_leave_minutes', 'overtime_minutes', 'updated_at',
        ])
        return

    tz = ZoneInfo(settings.APP_DEFAULT_TZ)
    first_session = closed_sessions[0]
    last_session = closed_sessions[-1]

    local_first_in = first_session.check_in_time.astimezone(tz)
    day = local_first_in.date()

    expected_start_dt = datetime.combine(day, rule.expected_start).replace(tzinfo=tz)
    expected_end_dt = datetime.combine(day, rule.expected_end).replace(tzinfo=tz)

    # Lateness — how late was the first check-in?
    late_delta = first_session.check_in_time - expected_start_dt
    late_minutes = max(0, int(late_delta.total_seconds() // 60))

    # Early leave — how early was the last check-out vs expected_end?
    early_delta = expected_end_dt - last_session.check_out_time
    early_leave_minutes = max(0, int(early_delta.total_seconds() // 60))

    # Overtime — how much did total work exceed the full expected shift length?
    expected_shift_minutes = int((expected_end_dt - expected_start_dt).total_seconds() // 60)
    overtime_raw = total_present - expected_shift_minutes
    threshold = rule.overtime_threshold_minutes
    overtime_minutes = max(0, overtime_raw - threshold) if overtime_raw > threshold else 0

    # Apply leave intervals to reduce late / early penalties
    leave_intervals = list(record.leave_intervals.all())
    if leave_intervals:
        for iv in leave_intervals:
            if late_minutes > 0:
                overlap_start = max(iv.start_time, expected_start_dt)
                overlap_end = min(iv.end_time, first_session.check_in_time)
                if overlap_end > overlap_start:
                    covered = int((overlap_end - overlap_start).total_seconds() // 60)
                    late_minutes = max(0, late_minutes - covered)

            if early_leave_minutes > 0:
                overlap_start = max(iv.start_time, last_session.check_out_time)
                overlap_end = min(iv.end_time, expected_end_dt)
                if overlap_end > overlap_start:
                    covered = int((overlap_end - overlap_start).total_seconds() // 60)
                    early_leave_minutes = max(0, early_leave_minutes - covered)

    record.total_present_minutes = total_present
    record.late_minutes = late_minutes
    record.early_leave_minutes = early_leave_minutes
    record.overtime_minutes = overtime_minutes
    record.save(update_fields=[
        'total_present_minutes', 'late_minutes',
        'early_leave_minutes', 'overtime_minutes', 'updated_at',
    ])


def recompute_compliance_for_record(record) -> None:
    """Compatibility shim — delegates to recompute_record_aggregates."""
    recompute_record_aggregates(record)
