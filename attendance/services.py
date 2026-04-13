"""
Attendance service layer.

Responsibilities:
- Extract and validate client IP against AttendanceSite.allowed_ip_ranges
- Compute overtime on check-out using the applicable ShiftRule
- Get or resolve the active AttendanceSite config
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
    Returns the first (leftmost) address, which is the original client.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def ip_in_allowed_ranges(ip: str, allowed_ranges: list[str]) -> bool:
    """
    Return True if `ip` falls within any of the CIDR ranges in `allowed_ranges`.
    Handles both IPv4 and IPv6 addresses gracefully.
    """
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
    """
    Return the first AttendanceSite row. Returns None if none configured yet.
    We use .first() — a single site is expected, but we don't enforce it at DB level.
    """
    from attendance.models import AttendanceSite
    return AttendanceSite.objects.first()


# ---------------------------------------------------------------------------
# Overtime calculation
# ---------------------------------------------------------------------------

def compute_overtime_minutes(
    user,
    check_in: datetime,
    check_out: datetime,
) -> int:
    """
    Determine overtime minutes for a completed attendance record.

    Lookup order:
    1. User's explicitly assigned ShiftRule (UserProfile.shift_rule)
    2. The default ShiftRule (is_default=True)
    3. No rule found → 0 overtime

    Returns integer minutes (0 if no applicable rule or no overtime).
    """
    rule = _get_shift_rule(user)
    if rule is None:
        return 0

    # Build expected_end as an aware datetime on the same calendar date as check_in
    tz = ZoneInfo(settings.APP_DEFAULT_TZ)
    local_check_in = check_in.astimezone(tz)
    expected_end_dt = datetime.combine(local_check_in.date(), rule.expected_end).replace(tzinfo=tz)

    threshold = timedelta(minutes=rule.overtime_threshold_minutes)
    overtime_delta = check_out - expected_end_dt

    if overtime_delta > threshold:
        return int(overtime_delta.total_seconds() // 60)

    return 0


def _get_shift_rule(user):
    """Shared helper — returns the applicable ShiftRule for a user or None."""
    from attendance.models import ShiftRule
    profile = getattr(user, 'profile', None)
    rule = getattr(profile, 'shift_rule', None)
    if rule is None or not rule.is_active:
        rule = ShiftRule.objects.filter(is_active=True, is_default=True).first()
    return rule


def compute_shift_compliance(
    user,
    check_in: datetime,
    check_out: datetime,
) -> tuple[int, int]:
    """
    Compute lateness and early-leave against the user's ShiftRule.

    Returns (late_minutes: int, early_leave_minutes: int).
    Both are 0 if on time / no rule found.
    """
    rule = _get_shift_rule(user)
    if rule is None:
        return 0, 0

    tz = ZoneInfo(settings.APP_DEFAULT_TZ)
    local_check_in = check_in.astimezone(tz)
    day = local_check_in.date()

    expected_start_dt = datetime.combine(day, rule.expected_start).replace(tzinfo=tz)
    expected_end_dt = datetime.combine(day, rule.expected_end).replace(tzinfo=tz)

    # Late: checked in after expected_start
    late_delta = check_in - expected_start_dt
    late_minutes = max(0, int(late_delta.total_seconds() // 60))

    # Early leave: checked out before expected_end
    early_delta = expected_end_dt - check_out
    early_leave_minutes = max(0, int(early_delta.total_seconds() // 60))

    return late_minutes, early_leave_minutes


# ---------------------------------------------------------------------------
# Check-in logic
# ---------------------------------------------------------------------------

def attempt_ip_checkin(request, user) -> tuple[bool, str | None]:
    """
    Try to check the user in via office IP.

    Returns (success: bool, failure_reason: str | None).
    failure_reason is None on success; one of:
      - 'site_not_configured'
      - 'no_ip_ranges_configured'
      - 'not_on_office_network'
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


def create_checkin_record(user, method: str, client_ip: str | None = None, override_reason: str = '') -> 'AttendanceRecord':
    """
    Create and return an AttendanceRecord for a successful (or pending override) check-in.
    Raises IntegrityError if a record already exists for today (caught in views).
    """
    from attendance.models import AttendanceRecord

    now = timezone.now()
    today = timezone.localdate()

    status = (
        AttendanceRecord.STATUS_PENDING
        if method == AttendanceRecord.METHOD_OVERRIDE
        else AttendanceRecord.STATUS_ACTIVE
    )

    return AttendanceRecord.objects.create(
        user=user,
        date=today,
        check_in_time=now,
        method=method,
        status=status,
        client_ip=client_ip,
        override_reason=override_reason,
    )
