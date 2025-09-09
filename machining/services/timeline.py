import time
from typing import Dict, Any, List, Optional
from django.db.models import Q
from ..models import Timer, Task

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
        same = (last['task_key'] == seg['task_key'] and last['is_hold'] == seg['is_hold'] and last['category'] == seg['category'])
        touching_or_overlap = seg['start_ms'] <= last['end_ms']
        if same and touching_or_overlap:
            if seg['end_ms'] > last['end_ms']:
                last['end_ms'] = seg['end_ms']
        else:
            out.append(seg)
    return out

def build_machine_timeline(machine_id: int, start_after_ms: Optional[int], start_before_ms: Optional[int]) -> Dict[str, Any]:
    # default to "today" if not provided
    if start_after_ms is None or start_before_ms is None:
        from django.utils import timezone
        from datetime import timedelta
        now_local = timezone.localtime()
        t0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        t1 = t0 + timedelta(days=1)
        start_after_ms = int(t0.timestamp() * 1000)
        start_before_ms = int(t1.timestamp() * 1000)

    now_ms = lambda: int(time.time() * 1000)

    # actual segments from timers (Timer → issue_key(Task) → machine_fk)
    timers = (
        Timer.objects
        .select_related('issue_key', 'machine_fk')
        .filter(machine_fk_id=machine_id)
        .filter(Q(finish_time__gte=start_after_ms) | Q(finish_time__isnull=True))
        .filter(start_time__lte=start_before_ms)
        .order_by('start_time')
    )

    actual: List[Dict[str, Any]] = []
    for t in timers:
        s = t.start_time
        e = t.finish_time or now_ms()
        s, e = _clamp_ms(s, e, start_after_ms, start_before_ms)
        if not s:
            continue
        is_hold = bool(getattr(t.issue_key, 'is_hold_task', False))
        actual.append({
            "start_ms": s,
            "end_ms": e,
            "task_key": t.issue_key_id if t.issue_key_id else None,
            "task_name": getattr(t.issue_key, 'name', None),
            "is_hold": is_hold,
            "category": "hold" if is_hold else "work",
        })
    actual = _merge_segments_ms(actual)

    # idle gaps
    idle: List[Dict[str, Any]] = []
    cursor = start_after_ms
    for seg in actual:
        if seg['start_ms'] > cursor:
            idle.append({
                "start_ms": cursor, "end_ms": seg['start_ms'],
                "task_key": None, "task_name": None,
                "is_hold": False, "category": "idle",
            })
        cursor = max(cursor, seg['end_ms'])
    if cursor < start_before_ms:
        idle.append({
            "start_ms": cursor, "end_ms": start_before_ms,
            "task_key": None, "task_name": None,
            "is_hold": False, "category": "idle",
        })

    def sum_secs_ms(rows, cat=None):
        tot = 0
        for r in rows:
            if cat and r['category'] != cat:
                continue
            tot += int((r['end_ms'] - r['start_ms']) / 1000)
        return tot

    return {
        "actual": actual,
        "idle": idle,
        "totals": {
            "productive_seconds": sum_secs_ms(actual, "work"),
            "hold_seconds": sum_secs_ms(actual, "hold"),
            "idle_seconds": sum_secs_ms(idle),
        }
    }
