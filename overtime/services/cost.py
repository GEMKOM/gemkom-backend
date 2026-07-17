# overtime/services/cost.py
"""
Cost / profit-impact calculation for overtime requests.

Reuses the existing labor-cost machinery:
  - tasks.services.costing._build_wage_picker / WAGE_MONTH_HOURS
  - machining.fx_utils.build_fx_lookup           (TRY -> EUR on a given date)
  - machining.services.timers.split_timer_by_local_day_and_bucket
  - projects.services.costing.build_job_cost_payload  (current cost & revenue)

Nothing here writes to the DB — it is a read-only projection used to show
approvers the financial impact of a request before they decide.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from tasks.services.costing import _build_wage_picker, WAGE_MONTH_HOURS
from machining.fx_utils import build_fx_lookup
from machining.services.timers import split_timer_by_local_day_and_bucket


_Q2 = Decimal("0.01")
_IST = ZoneInfo("Europe/Istanbul")


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_Q2, rounding=ROUND_HALF_UP)


def _dt_to_epoch_ms(dt) -> int:
    return int(dt.timestamp() * 1000)


def _bucket_multiplier(bucket: str, wage: dict, *, is_holiday: bool = False) -> Decimal:
    # Public holidays are priced at the Sunday rate (2x) — matching the existing
    # welding convention (WeldingTimeEntry: 'holiday' == "Holiday / Sunday (2x)").
    if is_holiday:
        return Decimal(str(wage["sunday_multiplier"]))
    if bucket == "after_hours":
        return Decimal(str(wage["after_hours_multiplier"]))
    if bucket == "sunday":
        return Decimal(str(wage["sunday_multiplier"]))
    return Decimal("1")  # weekday_work — normal rate (overtime rarely lands here)


def _holiday_dates_for_window(start_at, end_at) -> set:
    """
    Set of public-holiday dates (local) overlapping [start_at, end_at].
    Half-day holidays (Arife) are included: overtime runs after-hours, i.e. after
    the noon cut-off, so the whole overtime block on such a day is holiday-rate.
    """
    from attendance.models import PublicHoliday  # local import (avoid app-load cycles)
    s = start_at.astimezone(_IST).date()
    e = end_at.astimezone(_IST).date()
    return set(
        PublicHoliday.objects
        .filter(date__gte=s, date__lte=e)
        .values_list("date", flat=True)
    )


def compute_entry_overtime_cost_eur(user_id: int, start_at, end_at, *, pick_wage, fx, holiday_dates=None) -> Decimal:
    """
    Cost in EUR of a single operator working the [start_at, end_at] window,
    priced with their effective wage and the day/bucket split. Dates in
    ``holiday_dates`` are charged at the holiday (Sunday) multiplier.
    """
    if holiday_dates is None:
        holiday_dates = _holiday_dates_for_window(start_at, end_at)
    segments = split_timer_by_local_day_and_bucket(
        _dt_to_epoch_ms(start_at), _dt_to_epoch_ms(end_at), tz="Europe/Istanbul"
    )
    total = Decimal("0")
    for seg in segments:
        d = seg["date"]
        hours = Decimal(seg["seconds"]) / Decimal(3600)
        wage = pick_wage(user_id, d)
        if not wage:
            continue
        try_to_eur = fx(d)
        if try_to_eur == 0:
            continue
        base_hourly = Decimal(str(wage["base_monthly"])) / WAGE_MONTH_HOURS
        mult = _bucket_multiplier(seg["bucket"], wage, is_holiday=(d in holiday_dates))
        total += hours * base_hourly * mult * try_to_eur
    return total


def compute_request_cost_impact(request, *, only_approved: bool = False) -> dict:
    """
    Group the request's entries by job_no and, for each distinct job, report the
    current profit and the profit after this overtime is added, plus the total
    overtime cost across all jobs.

    ``only_approved`` restricts the calculation to entries with status='approved'
    (used after a decision); otherwise all entries are considered.
    """
    # Local import avoids a hard dependency at module import time.
    from projects.models import JobOrder
    from projects.services.costing import build_job_cost_payload

    entries = list(request.entries.all())
    if only_approved:
        entries = [e for e in entries if e.status == "approved"]

    user_ids = {e.user_id for e in entries}
    pick_wage = _build_wage_picker(user_ids)
    fx = build_fx_lookup("EUR")
    holiday_dates = _holiday_dates_for_window(request.start_at, request.end_at)

    # job_no -> {entries, overtime_cost}
    by_job: "OrderedDict[str, dict]" = OrderedDict()
    for e in entries:
        job_no = (e.job_no or "").strip()
        bucket = by_job.setdefault(job_no, {"overtime_cost": Decimal("0"), "count": 0})
        bucket["overtime_cost"] += compute_entry_overtime_cost_eur(
            e.user_id, request.start_at, request.end_at,
            pick_wage=pick_wage, fx=fx, holiday_dates=holiday_dates,
        )
        bucket["count"] += 1

    jobs = []
    total_overtime_cost = Decimal("0")
    for job_no, agg in by_job.items():
        overtime_cost = _q2(agg["overtime_cost"])
        total_overtime_cost += overtime_cost

        row = {
            "job_no": job_no,
            "title": None,
            "job_order_found": False,
            "entry_count": agg["count"],
            "current_selling_price_eur": None,
            "current_cost_eur": None,
            "current_profit_eur": None,
            "current_margin_pct": None,
            "overtime_cost_eur": str(overtime_cost),
            "projected_cost_eur": None,
            "projected_profit_eur": None,
            "projected_margin_pct": None,
        }

        job_order = None
        if job_no:
            job_order = (
                JobOrder.objects.select_related("cost_summary")
                .filter(job_no=job_no)
                .first()
            )

        if job_order is not None:
            payload = build_job_cost_payload(job_order)
            selling = Decimal(str(payload.get("selling_price_eur") or "0"))
            current_cost = Decimal(str(payload["actual"]["total_cost"] or "0"))
            current_profit = selling - current_cost
            projected_cost = current_cost + overtime_cost
            projected_profit = selling - projected_cost

            row.update(
                {
                    "title": getattr(job_order, "title", None) or getattr(job_order, "name", None),
                    "job_order_found": True,
                    "current_selling_price_eur": str(_q2(selling)),
                    "current_cost_eur": str(_q2(current_cost)),
                    "current_profit_eur": str(_q2(current_profit)),
                    "current_margin_pct": _margin_pct(current_profit, selling),
                    "projected_cost_eur": str(_q2(projected_cost)),
                    "projected_profit_eur": str(_q2(projected_profit)),
                    "projected_margin_pct": _margin_pct(projected_profit, selling),
                }
            )

        jobs.append(row)

    return {
        "request_id": request.id,
        "currency": "EUR",
        "total_overtime_cost_eur": str(_q2(total_overtime_cost)),
        "jobs": jobs,
    }


def _margin_pct(profit: Decimal, selling: Decimal):
    if selling and selling != 0:
        return str(_q2(profit / selling * Decimal("100")))
    return None
