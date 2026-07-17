# overtime/services/report.py
"""
Machining overtime report.

Lists approved overtime requests that carry machining operations and, for each
(operator, operation, overtime-day), shows whether that operation was actually
worked that day (from Timer logs) and for how long.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.contrib.contenttypes.models import ContentType

from tasks.models import Operation, Timer
from machining.services.timers import split_timer_by_local_day_and_bucket

from ..models import OvertimeEntry

IST = ZoneInfo("Europe/Istanbul")
_Q2 = Decimal("0.01")


def _hours(seconds) -> str:
    return str((Decimal(seconds) / Decimal(3600)).quantize(_Q2, rounding=ROUND_HALF_UP))


def _local_dates(start_at, end_at):
    """Local (Istanbul) calendar dates covered by [start_at, end_at)."""
    s = start_at.astimezone(IST).date()
    e = end_at.astimezone(IST).date()
    out, cur = [], s
    while cur <= e:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _date_bounds_ms(d):
    day_start = datetime.combine(d, time(0, 0), tzinfo=IST)
    day_end = day_start + timedelta(days=1)
    return int(day_start.timestamp() * 1000), int(day_end.timestamp() * 1000)


def build_machining_overtime_report(*, start_date=None, end_date=None, user_id=None, job_no=None):
    """
    Returns a flat list of report rows (dicts), one per (entry, operation, overtime-day).
    Filters are optional: start_date/end_date bound the overtime request window,
    user_id filters the operator, job_no filters the entry's job.
    """
    entries = (
        OvertimeEntry.objects
        .filter(request__status="approved", status="approved")
        .filter(operations__isnull=False)
        .select_related("request", "user")
        .prefetch_related("operations__part")
        .distinct()
    )
    if user_id:
        entries = entries.filter(user_id=user_id)
    if job_no:
        entries = entries.filter(job_no=job_no)
    if start_date:
        entries = entries.filter(request__end_at__date__gte=start_date)
    if end_date:
        entries = entries.filter(request__start_at__date__lte=end_date)

    entries = list(entries)
    if not entries:
        return []

    # Collect operations + users to fetch all relevant timers in one query.
    op_keys = set()
    user_ids = set()
    min_ms = None
    max_ms = None
    for e in entries:
        user_ids.add(e.user_id)
        for d in _local_dates(e.request.start_at, e.request.end_at):
            ds, de = _date_bounds_ms(d)
            min_ms = ds if min_ms is None else min(min_ms, ds)
            max_ms = de if max_ms is None else max(max_ms, de)
        for op in e.operations.all():
            op_keys.add(op.key)

    op_ct = ContentType.objects.get_for_model(Operation)
    timers = []
    if op_keys and user_ids and min_ms is not None:
        timers = list(
            Timer.objects.filter(
                content_type=op_ct,
                object_id__in=list(op_keys),
                user_id__in=list(user_ids),
                finish_time__isnull=False,
                start_time__lt=max_ms,
                finish_time__gt=min_ms,
            ).values("object_id", "user_id", "start_time", "finish_time")
        )

    # (op_key, user_id, date) -> worked seconds
    worked = defaultdict(int)
    for t in timers:
        for seg in split_timer_by_local_day_and_bucket(int(t["start_time"]), int(t["finish_time"])):
            worked[(t["object_id"], t["user_id"], seg["date"])] += seg["seconds"]

    rows = []
    for e in entries:
        req = e.request
        user_full = e.user.get_full_name() or e.user.username
        window_hours = str(Decimal(str(req.duration_hours)))
        for d in _local_dates(req.start_at, req.end_at):
            for op in e.operations.all():
                secs = worked.get((op.key, e.user_id, d), 0)
                rows.append({
                    "date": d.isoformat(),
                    "request_id": req.id,
                    "user_id": e.user_id,
                    "user_full_name": user_full,
                    "job_no": e.job_no,
                    "operation_key": op.key,
                    "operation_name": op.name,
                    "part_id": op.part_id,
                    "part_name": getattr(op.part, "name", None),
                    "worked": secs > 0,
                    "worked_hours": _hours(secs),
                    "overtime_window_hours": window_hours,
                })

    rows.sort(key=lambda r: (r["date"], r["request_id"], r["user_full_name"], r["operation_key"]))
    return rows
