# machining/services/reports.py
from datetime import datetime, timedelta, time
from typing import Dict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def _get_business_tz() -> ZoneInfo:
    """
    Use Istanbul unless overridden. Falls back to settings.TIME_ZONE,
    then to UTC as a last resort.
    """
    tzname = getattr(settings, "APP_DEFAULT_TZ", None) or getattr(settings, "TIME_ZONE", "UTC")
    try:
        return ZoneInfo(tzname)
    except Exception:
        return ZoneInfo("UTC")


def categorize_timer_segments(start_ms: int, finish_ms: int) -> Dict[str, float]:
    """
    Split a timer [start_ms, finish_ms) into:
      - weekday_work (Mon–Fri, 07:30–17:00 in APP_DEFAULT_TZ)
      - after_hours  (Mon–Fri outside 07:30–17:00 + all of Saturday)
      - sunday       (all of Sunday)

    Interprets epoch milliseconds as UTC, then converts to Europe/Istanbul
    (or APP_DEFAULT_TZ) to compute overlaps.
    Returns seconds in each bucket (float).
    """
    tz_business = _get_business_tz()

    # 1) epoch-ms -> aware UTC datetimes
    start_utc = datetime.fromtimestamp(start_ms / 1000, tz=ZoneInfo("UTC"))
    end_utc   = datetime.fromtimestamp(finish_ms / 1000, tz=ZoneInfo("UTC"))
    if end_utc <= start_utc:
        return {"weekday_work": 0.0, "after_hours": 0.0, "sunday": 0.0}

    # 2) convert to business tz (Europe/Istanbul)
    start = timezone.localtime(start_utc, tz_business)
    end   = timezone.localtime(end_utc,   tz_business)

    buckets = {"weekday_work": 0.0, "after_hours": 0.0, "sunday": 0.0}

    cur = start
    while cur < end:
        # Day boundaries in business tz (robust if DST ever comes back)
        day_start = datetime.combine(cur.date(), time(0, 0), tz_business)
        day_end = day_start + timedelta(days=1)
        nxt = min(day_end, end)

        weekday = cur.weekday()  # 0=Mon ... 6=Sun

        # Work window (only Mon–Fri)
        work_start = datetime.combine(cur.date(), time(7, 30), tz_business)
        work_end   = datetime.combine(cur.date(), time(17, 0), tz_business)

        if 0 <= weekday <= 4:
            # overlap with work window
            overlap_start = max(cur, work_start)
            overlap_end   = min(nxt, work_end)
            work_secs = max(0.0, (overlap_end - overlap_start).total_seconds())

            day_secs   = (nxt - cur).total_seconds()
            after_secs = max(0.0, day_secs - work_secs)

            buckets["weekday_work"] += work_secs
            buckets["after_hours"]  += after_secs

        elif weekday == 5:  # Saturday
            buckets["after_hours"] += (nxt - cur).total_seconds()

        else:               # Sunday
            buckets["sunday"] += (nxt - cur).total_seconds()

        cur = nxt

    return buckets
