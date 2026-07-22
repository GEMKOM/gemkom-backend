"""
Working-day (iş günü) date arithmetic for production planning.

Day valuation matches vacation_requests' ``_working_days_in_range``:
weekends count 0, full public holidays count 0, half-day holidays
(Arife) count 0.5, ordinary weekdays count 1.

Lateness semantics — ``working_day_delta(planned, actual)`` is signed and
sums day values over a half-open interval (planned, actual]:

* same day               -> 0    (finishing ON the target date is on time)
* actual after planned   -> +working days in (planned, actual]   (late)
* actual before planned  -> -working days in (actual, planned]   (early)

Consequences: a Friday target completed on Saturday or Sunday is 0 (still
on time in working-day terms); completed the following Monday is +1; if
the actual day itself is an Arife it contributes 0.5.
"""
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

TURKEY_TZ = ZoneInfo('Europe/Istanbul')

ZERO = Decimal('0')
HALF = Decimal('0.5')
ONE = Decimal('1')


def local_date(dt):
    """Istanbul calendar date of an aware datetime (None-safe).

    completed_at/started_at are stored UTC; a 00:30 Istanbul completion is
    still the previous day in UTC, so never use ``dt.date()`` directly.
    """
    if dt is None:
        return None
    return dt.astimezone(TURKEY_TZ).date()


def today_local():
    """Today's calendar date in Istanbul."""
    return timezone.now().astimezone(TURKEY_TZ).date()


def load_holiday_calendar(start, end):
    """One PublicHoliday query for [start, end] -> {date: Decimal day value}.

    Full holidays map to 0, half-day holidays (Arife) to 0.5. Dates absent
    from the dict are ordinary days (valued by ``day_value``).
    """
    from attendance.models import PublicHoliday

    calendar = {}
    rows = PublicHoliday.objects.filter(
        date__gte=start, date__lte=end
    ).values('date', 'is_half_day')
    for row in rows:
        calendar[row['date']] = HALF if row['is_half_day'] else ZERO
    return calendar


def day_value(d, calendar):
    """Working-day value of a single date: 0 weekend/full holiday, 0.5 Arife, else 1."""
    if d.weekday() >= 5:
        return ZERO
    return calendar.get(d, ONE)


def working_day_delta(planned, actual, calendar):
    """Signed working days from planned to actual (see module docstring).

    Returns a Decimal (multiples of 0.5), or None if either date is missing.
    """
    if planned is None or actual is None:
        return None
    if actual == planned:
        return ZERO
    if actual > planned:
        sign, first, last = ONE, planned + timedelta(days=1), actual
    else:
        sign, first, last = -ONE, actual + timedelta(days=1), planned
    total = ZERO
    current = first
    while current <= last:
        total += day_value(current, calendar)
        current += timedelta(days=1)
    return sign * total
