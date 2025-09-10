from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from django.utils import timezone
from .models import MachineCalendar

DOW_MON = 0  # ISO weekday: Monday=0 ... Sunday=6

def _hm_to_minutes(hhmm: str) -> int:
    hh, mm = hhmm.split(':')
    return int(hh) * 60 + int(mm)

def _shifts_for_dow(template: Dict[str, Any], dow: int) -> List[Dict[str, Any]]:
    # template uses "0".."6" (Mon..Sun)
    return list(template.get(str(dow), []))

def _localize_ms(ms: int, tz_name: str) -> datetime:
    tz = timezone.pytz.timezone(tz_name) if hasattr(timezone, 'pytz') else timezone.get_current_timezone()
    # ms is epoch milliseconds
    return datetime.fromtimestamp(ms / 1000.0, tz)

def _minutes_since_local_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute

def _allowed_interval_spans(shifts: List[Dict[str, Any]]) -> List[range]:
    """
    Convert day shifts to minute ranges.
    Normal: start<=end -> [start, end)
    Overnight: end_next_day -> [start, end+1440)
    """
    spans = []
    for s in shifts:
        start = _hm_to_minutes(s['start'])
        end = _hm_to_minutes(s['end'])
        if s.get('end_next_day'):
            end += 1440
        if end > start:
            spans.append(range(start, end))
    return spans

def validate_bar_within_calendar(machine_id: int, start_ms: int, end_ms: int) -> Optional[str]:
    """
    Returns None if valid.
    Returns a human-readable error string if the [start_ms, end_ms) bar does not fit entirely within
    a single allowed shift window for that machine calendar.
    Policy: frontend must split bars at non-working boundaries (we don't auto-split server-side).
    """
    if end_ms is None or start_ms is None or end_ms <= start_ms:
        return "planned_end_ms must be greater than planned_start_ms."

    try:
        cal = MachineCalendar.objects.select_related('machine_fk').get(machine_fk_id=machine_id)
    except MachineCalendar.DoesNotExist:
        return None  # No calendar configured → accept anything (or tighten to reject; your call)

    # Convert to local tz for that machine
    tz_name = cal.timezone or 'Europe/Istanbul'
    start_local = _localize_ms(start_ms, tz_name)
    end_local   = _localize_ms(end_ms, tz_name)

    # We only accept bars that fit inside ONE shift window.
    # Compute a "span" in minutes relative to start's local day.
    start_day = start_local.date()
    end_day = end_local.date()

    # Handle a bar that can legitimately end next local day if a shift crosses midnight.
    day_delta = (end_day - start_day).days
    total_minutes = (end_local - start_local).total_seconds() / 60.0
    if day_delta < 0:
        return "planned interval crosses days in reverse."
    if day_delta > 1:
        return "planned interval crosses more than one local day. Split it into day-sized bars."

    # Minutes since start_day midnight; if it ends next day, add 1440
    start_min = _minutes_since_local_midnight(start_local)
    end_min = _minutes_since_local_midnight(end_local) + (1440 if day_delta == 1 else 0)

    # Pull allowed spans for the start day-of-week
    dow = (start_local.weekday())  # Monday=0
    shifts = _shifts_for_dow(cal.week_template or {}, dow)
    spans = _allowed_interval_spans(shifts)

    if not spans:
        return "No working shifts configured for the selected day."

    # Check containment
    for span in spans:
        if start_min in span and (end_min - 1) in span:  # end is exclusive
            return None

    return "Planned bar falls outside working hours. Split at breaks or adjust times."