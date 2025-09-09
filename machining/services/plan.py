# machining/services/plan.py
from typing import Optional, Dict, Any, List
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from ..models import Task  # relative import from machining app

def _parse_ms(val: Optional[str]) -> Optional[int]:
    if val is None:
        return None
    ts = int(val)
    if ts < 1_000_000_000_000:  # seconds -> ms
        ts *= 1000
    return ts

def _clamp_ms(s: Optional[int], e: Optional[int], t0: int, t1: int):
    if s is None or e is None:
        return (None, None)
    s = max(s, t0)
    e = min(e, t1)
    return (s, e) if e > s else (None, None)

def build_machine_plan(machine_id: int,
                       start_after_ms: Optional[int],
                       start_before_ms: Optional[int]) -> Dict[str, Any]:
    # Default to today's window (server TZ) if not provided
    if start_after_ms is None or start_before_ms is None:
        now_local = timezone.localtime()
        t0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        t1 = t0 + timedelta(days=1)
        start_after_ms = int(t0.timestamp() * 1000)
        start_before_ms = int(t1.timestamp() * 1000)

    # Query only tasks with a plan overlapping the window
    qs = (
        Task.objects
        .select_related('machine_fk')
        .filter(machine_fk_id=machine_id)
        .filter(planned_start_ms__isnull=False, planned_end_ms__isnull=False)
        .filter(planned_start_ms__lte=start_before_ms,
                planned_end_ms__gte=start_after_ms)
        .order_by('plan_order', 'planned_start_ms', 'key')
    )

    segments: List[Dict[str, Any]] = []
    for tk in qs:
        s, e = _clamp_ms(tk.planned_start_ms, tk.planned_end_ms,
                         start_after_ms, start_before_ms)
        if not s:
            continue
        segments.append({
            "start_ms": s,
            "end_ms": e,
            "task_key": tk.key,
            "task_name": tk.name,
            "is_hold": bool(tk.is_hold_task),
            "category": "planned",
            "plan_order": tk.plan_order,
            "plan_locked": bool(tk.plan_locked),
            "machine_id": tk.machine_fk_id,
        })

    # Optional soft validation: overlapping items with same plan_order
    overlaps = []
    by_order: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for seg in segments:
        by_order.setdefault(seg["plan_order"], []).append(seg)
    for order, items in by_order.items():
        items.sort(key=lambda x: x["start_ms"])
        for i in range(1, len(items)):
            prev, cur = items[i-1], items[i]
            if cur["start_ms"] < prev["end_ms"]:
                overlaps.append({
                    "plan_order": order,
                    "prev_task": prev["task_key"],
                    "cur_task": cur["task_key"],
                })

    return {"planned": segments, "overlaps": overlaps}
