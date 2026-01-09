from typing import Dict, Any, List, Optional
from django.db.models import Q

from machines.calendar import DEFAULT_WEEK_TEMPLATE, _get_calendar
from machines.models import Machine
from tasks.models import Timer
from datetime import datetime, timedelta, time as dtime
from django.utils import timezone

MAX_DAYS = 7
MAX_WINDOW_MS = MAX_DAYS * 24 * 60 * 60 * 1000

def _default_last_7_full_days_ms():
    now_local = timezone.localtime()
    # Start = midnight today minus 6 days (=> 7 full days including today)
    start_day = (now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=MAX_DAYS - 1))
    end_day = start_day + timedelta(days=MAX_DAYS)  # midnight after the 7th day
    return int(start_day.timestamp() * 1000), int(end_day.timestamp() * 1000)

def _ensure_valid_range(start_after_ms, start_before_ms):
    # Fill defaults
    if start_after_ms is None or start_before_ms is None:
        start_after_ms, start_before_ms = _default_last_7_full_days_ms()
    # Normalize seconds → ms if needed
    if start_after_ms is not None and start_after_ms < 1_000_000_000_000:
        start_after_ms *= 1000
    if start_before_ms is not None and start_before_ms < 1_000_000_000_000:
        start_before_ms *= 1000
    # Validate ordering
    if start_after_ms >= start_before_ms:
        raise ValueError("start_after must be earlier than start_before")
    # Enforce max window
    if (start_before_ms - start_after_ms) > MAX_WINDOW_MS:
        raise OverflowError(f"Range too large. Max allowed window is {MAX_DAYS} full days.")
    return start_after_ms, start_before_ms

def _clamp_ms(s: int, e: int, t0: int, t1: int):
    s = max(s, t0) if t0 is not None else s
    e = min(e, t1) if t1 is not None else e
    return (s, e) if s is not None and e is not None and e > s else (None, None)

def _merge_segments_ms(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    rows.sort(key=lambda r: r['start_ms'])
    out = [rows[0]]
    for seg in rows[1:]:
        last = out[-1]
        same = (last['task_key'] == seg['task_key'] and last['category'] == seg['category'])
        touching_or_overlap = seg['start_ms'] <= last['end_ms']
        if same and touching_or_overlap:
            if seg['end_ms'] > last['end_ms']:
                last['end_ms'] = seg['end_ms']
        else:
            out.append(seg)
    return out

def _sum_secs(rows, cat=None):
    tot = 0
    for r in rows:
        if cat and r['category'] != cat: 
            continue
        tot += int((r['end_ms'] - r['start_ms']) / 1000)
    return tot

def _parse_hhmm(hhmm: str):
    h, m = map(int, hhmm.split(":"))
    return dtime(hour=h, minute=m)

from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from django.utils import timezone
from django.db.models import Q
from machines.models import Machine  # has OneToOne 'calendar'


def _parse_hhmm(hhmm: str) -> dtime:
    h, m = map(int, hhmm.split(":"))
    return dtime(hour=h, minute=m)


def _iter_calendar_windows_from(tzname: str,
                                week_template: Dict[str, List[Dict[str, Any]]],
                                work_exceptions: List[Dict[str, Any]],
                                start_after_ms: int,
                                start_before_ms: int,
                                now_cutoff_ms: int):
    """
    Yield working windows [ws,we] in ms based on the provided tz/template/exceptions.
    - Windows are clipped to [start_after_ms, min(start_before_ms, now_cutoff_ms)]
    - Supports overnight shifts with {"end_next_day": true}
    - Exceptions: [{"date":"YYYY-MM-DD","closed":true}|{"date":"YYYY-MM-DD","shifts":[...]}]
    """
    effective_end_ms = min(start_before_ms, now_cutoff_ms)
    if start_after_ms >= effective_end_ms:
        return
        yield  # keep generator semantics

    tz = ZoneInfo(tzname or "Europe/Istanbul")
    start_dt = datetime.fromtimestamp(start_after_ms / 1000, tz)
    end_dt   = datetime.fromtimestamp(effective_end_ms / 1000, tz)

    exc_map = {exc.get("date"): exc for exc in (work_exceptions or []) if exc.get("date")}

    day = start_dt.date()
    last_date = (end_dt - timedelta(milliseconds=1)).date()
    while day <= last_date:
        key = str(day.weekday())  # "0".."6"
        shifts = list((week_template or {}).get(key, []))

        # apply day-level exception
        exc = exc_map.get(day.isoformat())
        if exc:
            if exc.get("closed"):
                shifts = []
            elif "shifts" in exc:
                shifts = list(exc["shifts"])

        for sh in shifts:
            try:
                s_local = datetime.combine(day, _parse_hhmm(sh["start"])).replace(tzinfo=tz)
                end_day = day + timedelta(days=1) if sh.get("end_next_day") else day
                e_local = datetime.combine(end_day, _parse_hhmm(sh["end"])).replace(tzinfo=tz)
            except Exception:
                continue

            ws = max(int(s_local.timestamp() * 1000), start_after_ms)
            we = min(int(e_local.timestamp() * 1000), effective_end_ms)
            if we > ws:
                yield (ws, we)
        day += timedelta(days=1)


def _subtract_actual_gaps_within_window(actual_sorted, ws, we):
    """
    Return idle gaps within [ws,we], subtracting merged actual segments that intersect this window.
    Idle is strictly clipped to the window, so it never leaks past shift end or bridges nights.
    """
    idle = []
    cursor = ws
    for seg in actual_sorted:
        if seg["end_ms"] <= ws:
            continue
        if seg["start_ms"] >= we:
            break
        a = max(seg["start_ms"], ws)  # clip to window start
        b = min(seg["end_ms"], we)    # clip to window end
        if a > cursor:
            idle.append({
                "start_ms": cursor, "end_ms": a,
                "task_key": None, "task_name": None,
                "is_hold": False, "category": "idle",
            })
        cursor = max(cursor, b)
    if cursor < we:
        idle.append({
            "start_ms": cursor, "end_ms": we,
            "task_key": None, "task_name": None,
            "is_hold": False, "category": "idle",
        })
    return idle


def _build_bulk_machine_timelines(machine_ids, start_after_ms, start_before_ms):
    """
    - Active timers (finish_time is null) are shown up to 'now'.
    - Idle exists only inside working windows (calendar or default template) and never in the future.
    - Idle never crosses shift boundaries (e.g., 16:30→17:00 only; no overnight bridging).
    """
    now_ms = int(timezone.now().timestamp() * 1000)

    # preload machines (and calendar via OneToOne)
    machines = (
        Machine.objects
        .filter(id__in=machine_ids)
        .select_related("calendar")
        .only("id", "name", "calendar__timezone", "calendar__week_template", "calendar__work_exceptions")
    )

    # Prepare tz/template/exceptions per machine using your _get_calendar
    cal_info = {}
    for m in machines:
        tzname, week, exceptions = _get_calendar(m)  # <- you provided this
        # normalize keys to strings "0".."6" just in case
        week = {str(k): v for k, v in week.items()}
        cal_info[m.id] = (tzname, week, exceptions)

    # Pull timers intersecting requested range
    timers = (
        Timer.objects
        .prefetch_related('issue_key').select_related('machine_fk')
        .filter(machine_fk_id__in=machine_ids)
        .filter(Q(finish_time__gte=start_after_ms) | Q(finish_time__isnull=True))
        .filter(start_time__lte=start_before_ms)
        .order_by('start_time')
    )

    # Group/prepare actual segments (active timers → end at now, and nothing goes into the future)
    grouped = {mid: [] for mid in machine_ids}
    for t in timers:
        mid = t.machine_fk_id
        if mid is None:
            continue
        s = max(t.start_time, start_after_ms)
        e = min((t.finish_time or now_ms), start_before_ms, now_ms)
        if e <= s:
            continue
        # Note: is_hold_task is deprecated (legacy Task model concept)
        # Operations don't have this field, so we treat all work as productive
        grouped[mid].append({
            "start_ms": s,
            "end_ms": e,
            "task_key": getattr(t.issue_key, 'pk', None),
            "task_name": getattr(t.issue_key, 'name', None),
            "is_hold": False,
            "category": "work",
            "timer_id": t.id,
        })

    results = {}
    for mid in machine_ids:
        actual = _merge_segments_ms(grouped.get(mid, []))  # you already have this helper

        # Build idle strictly per working window and never past 'now'
        idle = []
        tzname, week, exceptions = cal_info.get(mid, ("Europe/Istanbul", DEFAULT_WEEK_TEMPLATE, []))
        for ws, we in _iter_calendar_windows_from(tzname, week, exceptions, start_after_ms, start_before_ms, now_ms):
            idle.extend(_subtract_actual_gaps_within_window(actual, ws, we))

        segments = sorted(actual + idle, key=lambda r: r["start_ms"])
        totals = {
            "productive_seconds": _sum_secs(segments, "work"),
            "hold_seconds": _sum_secs(segments, "hold"),
            "idle_seconds": _sum_secs(segments, "idle"),
        }
        results[mid] = {"segments": segments, "totals": totals}

    return results