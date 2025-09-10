# machining/services/calendar.py
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from machines.models import Machine, MachineCalendar  # adjust if Machine lives elsewhere

# DEFAULT: Mon–Fri 07:30–12:00 & 12:30–17:00; Sat/Sun closed (lunch 12:00–12:30)
DEFAULT_WEEK_TEMPLATE: Dict[str, List[Dict[str, Any]]] = {
    "0": [ {"start":"07:30","end":"12:00"}, {"start":"12:30","end":"17:00"} ],
    "1": [ {"start":"07:30","end":"12:00"}, {"start":"12:30","end":"17:00"} ],
    "2": [ {"start":"07:30","end":"12:00"}, {"start":"12:30","end":"17:00"} ],
    "3": [ {"start":"07:30","end":"12:00"}, {"start":"12:30","end":"17:00"} ],
    "4": [ {"start":"07:30","end":"12:00"}, {"start":"12:30","end":"17:00"} ],
    "5": [],
    "6": [],
}

def _get_calendar(machine: Machine) -> Tuple[str, Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """
    Return (timezone, week_template, work_exceptions) for the machine.
    Falls back to defaults if no MachineCalendar exists or fields are empty.
    """
    tz = getattr(settings, "APP_DEFAULT_TZ", "Europe/Istanbul")
    week = DEFAULT_WEEK_TEMPLATE
    exceptions: List[Dict[str, Any]] = []

    cal: Optional[MachineCalendar] = getattr(machine, "calendar", None)
    if cal is not None:
        tz = cal.timezone or tz
        if cal.week_template:
            # normalize to "0".."6" keys as strings
            week = {str(k): v for k, v in cal.week_template.items()}
        if cal.work_exceptions:
            exceptions = cal.work_exceptions

    return tz, week, exceptions

def _hhmm_to_time(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))

def _parse_windows_for_day(tz: ZoneInfo, d: date, windows_json: List[Dict[str, Any]]):
    """
    Turn a list of {'start','end', ['end_next_day']} into aware datetimes for local date d.
    """
    out: List[Tuple[datetime, datetime]] = []
    for w in windows_json or []:
        s = datetime.combine(d, _hhmm_to_time(w["start"]), tz)
        e = datetime.combine(d + (timedelta(days=1) if w.get("end_next_day") else timedelta(0)),
                             _hhmm_to_time(w["end"]), tz)
        if e > s:
            out.append((s, e))
    return out

def _windows_for_date(machine: Machine, d: date) -> List[Tuple[datetime, datetime]]:
    """
    Working windows for local date d:
      - Exceptions override the day entirely.
      - Otherwise, use weekly template.
      - Include previous day's overnight tails (00:00..end) where `end_next_day=true`.
    """
    tz_name, week, exceptions = _get_calendar(machine)
    tz = ZoneInfo(tz_name)

    # exceptions for today
    ex_today = next((e for e in exceptions if e.get("date") == d.isoformat()), None)
    today_windows = _parse_windows_for_day(tz, d, ex_today.get("windows", [])) if ex_today else \
                    _parse_windows_for_day(tz, d, week.get(str(d.weekday()), []))

    # tails from previous day's overnight windows
    prev = d - timedelta(days=1)
    ex_prev = next((e for e in exceptions if e.get("date") == prev.isoformat()), None)
    prev_src = ex_prev.get("windows", []) if ex_prev else week.get(str(prev.weekday()), []) or []

    for w in prev_src:
        if w.get("end_next_day"):
            s = datetime.combine(d, time(0, 0), tz)
            e = datetime.combine(d, _hhmm_to_time(w["end"]), tz)
            if e > s:
                today_windows.append((s, e))

    today_windows.sort(key=lambda x: x[0])
    return today_windows

def _split_interval_by_day(machine: Machine, start_ms: int, end_ms: int):
    tz_name, _, _ = _get_calendar(machine)
    tz = ZoneInfo(tz_name)
    s = datetime.fromtimestamp(start_ms/1000, tz)
    e = datetime.fromtimestamp(end_ms/1000, tz)
    parts = []
    cur = s
    while cur < e:
        day_end = datetime(cur.year, cur.month, cur.day, 23, 59, 59, 999000, tz)
        seg_end = min(e, day_end)
        parts.append((cur.date(), cur, seg_end))
        cur = seg_end + timedelta(milliseconds=1)
    return parts

def validate_plan_interval(machine: Machine, start_ms: int, end_ms: int) -> Optional[str]:
    """
    Return None if valid; else a helpful error string pointing to the violating local date & allowed windows.
    """
    if end_ms <= start_ms:
        return "planned_end_ms must be greater than planned_start_ms"
    for d, seg_s, seg_e in _split_interval_by_day(machine, start_ms, end_ms):
        windows = _windows_for_date(machine, d)
        covered = any(seg_s >= w_s and seg_e <= w_e for (w_s, w_e) in windows)
        if not covered:
            slots = ", ".join([f"{w_s.strftime('%H:%M')}-{w_e.strftime('%H:%M')}" for w_s, w_e in windows]) or "closed"
            return f"{d.isoformat()} not within working windows ({slots})"
    return None
