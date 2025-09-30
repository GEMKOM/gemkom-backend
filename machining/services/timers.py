# machining/services/reports.py
from datetime import datetime, timedelta, time
from typing import Dict
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

IST = ZoneInfo("Europe/Istanbul")

W_START = time(7, 30)   # weekday window start
W_END   = time(17, 0)   # weekday window end

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


def _clip(a: datetime, b: datetime, start: datetime, end: datetime) -> int:
    s = max(a, start)
    e = min(b, end)
    return max(0, int((e - s).total_seconds()))

def split_timer_by_local_day_and_bucket(start_ms: int, finish_ms: int, tz="Europe/Istanbul"):
    """
    Returns a list of {date, bucket, seconds} segments where bucket is:
      - 'weekday_work' (Mon-Fri 07:30-17:00)
      - 'after_hours'  (Mon-Sat outside weekday window)
      - 'sunday'       (Sunday all day)
    """
    z = ZoneInfo(tz)
    a = datetime.fromtimestamp(start_ms/1000, tz=z)
    b = datetime.fromtimestamp(finish_ms/1000, tz=z)
    if b <= a:
        return []

    out = []
    cur = a
    while cur.date() <= b.date():
        day_start = datetime.combine(cur.date(), time(0,0), tzinfo=z)
        day_end   = day_start + timedelta(days=1)

        span_start = max(a, day_start)
        span_end   = min(b, day_end)
        seconds = int((span_end - span_start).total_seconds())
        if seconds <= 0:
            cur = day_end
            continue

        dow = span_start.weekday()  # Mon=0 ... Sun=6
        if dow == 6:  # Sunday
            out.append({"date": span_start.date(), "bucket": "sunday", "seconds": seconds})
        else:
            # weekday window within the day
            ww_start_dt = datetime.combine(span_start.date(), W_START, tzinfo=z)
            ww_end_dt   = datetime.combine(span_start.date(), W_END, tzinfo=z)

            ww = _clip(span_start, span_end, ww_start_dt, ww_end_dt)
            ah = seconds - ww  # the rest of the day (including Sat) is after-hours

            if ww > 0:
                out.append({"date": span_start.date(), "bucket": "weekday_work", "seconds": ww})
            if ah > 0:
                out.append({"date": span_start.date(), "bucket": "after_hours", "seconds": ah})

        cur = day_end

    return out