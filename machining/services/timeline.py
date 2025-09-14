import time
from typing import Dict, Any, List, Optional
from django.db.models import Q

from machines.models import Machine
from ..models import Timer, Task
from datetime import timedelta
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

def _iter_calendar_windows(cal, start_after_ms: int, start_before_ms: int):
    """
    Yield working windows [ws, we] (ms) within the requested range based on the machine's calendar.
    Supports overnight shifts when {'end_next_day': True}.
    If no calendar or empty template, yield the entire range once.
    """
    if not cal or not cal.week_template:
        yield (start_after_ms, start_before_ms)
        return

    tzname = cal.timezone or "Europe/Istanbul"
    tz = timezone.pytz.timezone(tzname) if hasattr(timezone, "pytz") else timezone.get_current_timezone()

    start_dt = datetime.fromtimestamp(start_after_ms / 1000, tz)
    end_dt   = datetime.fromtimestamp(start_before_ms / 1000, tz)

    # (Optional) quick map of exceptions: {"YYYY-MM-DD": {"shifts":[...]} or {"closed":True}}
    exc_map = {}
    for exc in (cal.work_exceptions or []):
        day = exc.get("date")
        if day:
            exc_map[day] = exc

    day = start_dt.date()
    while day <= (end_dt - timedelta(milliseconds=1)).date():
        key = str(day.weekday())  # 0..6 (Mon..Sun)
        shifts = list(cal.week_template.get(key, []))

        # Apply exception override if any
        exc = exc_map.get(day.isoformat())
        if exc:
            if exc.get("closed"):
                shifts = []
            elif "shifts" in exc:
                shifts = list(exc["shifts"])

        for sh in shifts:
            try:
                s_local = tz.localize(datetime.combine(day, _parse_hhmm(sh["start"])))
                end_day = day + timedelta(days=1) if sh.get("end_next_day") else day
                e_local = tz.localize(datetime.combine(end_day, _parse_hhmm(sh["end"])))
            except Exception:
                continue  # skip malformed shift

            # clip to requested range
            ws = max(int(s_local.timestamp() * 1000), start_after_ms)
            we = min(int(e_local.timestamp() * 1000), start_before_ms)
            if we > ws:
                yield (ws, we)

        day += timedelta(days=1)

def _subtract_actual_gaps_within_window(actual_sorted, ws, we):
    """
    Given merged & time-ordered actual segments, return idle gaps within [ws,we].
    actual_sorted: list of dicts with start_ms, end_ms (work or hold).
    """
    idle = []
    cursor = ws
    # advance to first segment that might intersect window
    for seg in actual_sorted:
        if seg["end_ms"] <= ws:
            continue
        if seg["start_ms"] >= we:
            break
        a = max(seg["start_ms"], ws)
        b = min(seg["end_ms"], we)
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
    One-pass fetch for all relevant timers, grouped per machine, then build
    calendar-aware idle (idle only inside MachineCalendar windows).
    """
    now_ms = lambda: int(timezone.now().timestamp() * 1000)

    # fetch calendars up-front
    machines = (
        Machine.objects
        .filter(id__in=machine_ids)
        .select_related("calendar")
        .only("id", "calendar__timezone", "calendar__week_template", "calendar__work_exceptions")
    )
    cal_by_id = {m.id: getattr(m, "calendar", None) for m in machines}

    timers = (
        Timer.objects
        .select_related('issue_key', 'machine_fk')
        .filter(machine_fk_id__in=machine_ids)
        .filter(Q(finish_time__gte=start_after_ms) | Q(finish_time__isnull=True))
        .filter(start_time__lte=start_before_ms)
        .order_by('start_time')
    )

    # Group actual timers by machine
    grouped = {mid: [] for mid in machine_ids}
    for t in timers:
        mid = t.machine_fk_id
        if mid is None:
            continue
        s = t.start_time
        e = t.finish_time or now_ms()
        s, e = _clamp_ms(s, e, start_after_ms, start_before_ms)
        if not s:
            continue
        is_hold = bool(getattr(t.issue_key, 'is_hold_task', False))
        grouped[mid].append({
            "start_ms": s,
            "end_ms": e,
            "task_key": getattr(t.issue_key, 'pk', None),
            "task_name": getattr(t.issue_key, 'name', None),
            "is_hold": is_hold,
            "category": "hold" if is_hold else "work",
        })

    results = {}
    for mid in machine_ids:
        actual = _merge_segments_ms(grouped.get(mid, []))  # merged work/hold
        # Build idle only inside calendar windows:
        idle = []
        cal = cal_by_id.get(mid)
        for ws, we in _iter_calendar_windows(cal, start_after_ms, start_before_ms):
            idle.extend(_subtract_actual_gaps_within_window(actual, ws, we))

        segments = sorted(actual + idle, key=lambda r: r["start_ms"])
        totals = {
            "productive_seconds": _sum_secs(segments, "work"),
            "hold_seconds": _sum_secs(segments, "hold"),
            "idle_seconds": _sum_secs(segments, "idle"),
        }
        results[mid] = {"segments": segments, "totals": totals}
    return results