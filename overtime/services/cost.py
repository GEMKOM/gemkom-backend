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


# Overtime rate buckets. Overtime is by definition worked outside normal hours,
# so there is no 1x bucket here: every hour carries a premium.
OVERTIME_BUCKETS = ("weekday", "saturday", "sunday", "holiday")


def classify_overtime_day(d, holiday_dates) -> str:
    """
    Which overtime rate bucket a local calendar date falls in.

    Deliberately date-based, not time-of-day based: an overtime request is
    already outside working hours by definition, so the 07:30-17:00 window that
    `split_timer_by_local_day_and_bucket` applies to regular timer logs must not
    be used to discount it.

    A public holiday that falls on a Sunday is reported as 'holiday' (checked
    first). The two carry the same multiplier, so only the attribution differs.
    """
    if d in holiday_dates:
        return "holiday"
    dow = d.weekday()  # Mon=0 ... Sun=6
    if dow == 6:
        return "sunday"
    if dow == 5:
        return "saturday"
    return "weekday"


def overtime_multiplier(bucket: str, wage: dict) -> Decimal:
    """
    weekday   -> after_hours_multiplier (1.5x default)
    saturday  -> after_hours_multiplier (1.5x default)
    sunday    -> sunday_multiplier      (2x default)
    holiday   -> sunday_multiplier      (2x default)

    Reads the per-user WageRate multipliers, so individual overrides still apply.
    Saturday and weekday share a rate but stay separate buckets so the report can
    report them apart; likewise sunday and holiday.
    """
    if bucket in ("sunday", "holiday"):
        return Decimal(str(wage["sunday_multiplier"]))
    return Decimal(str(wage["after_hours_multiplier"]))


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


def hours_by_local_day(start_at, end_at) -> "OrderedDict":
    """
    {local date -> Decimal hours} for the window. Uses the shared day splitter
    for the midnight boundaries but collapses its time-of-day buckets, which do
    not apply to overtime (see classify_overtime_day).
    """
    per_day: "OrderedDict[object, Decimal]" = OrderedDict()
    for seg in split_timer_by_local_day_and_bucket(
        _dt_to_epoch_ms(start_at), _dt_to_epoch_ms(end_at), tz="Europe/Istanbul"
    ):
        hours = Decimal(seg["seconds"]) / Decimal(3600)
        if hours > 0:
            per_day[seg["date"]] = per_day.get(seg["date"], Decimal("0")) + hours
    return per_day


def compute_entry_overtime_cost_eur(user_id: int, start_at, end_at, *, pick_wage, fx, holiday_dates=None) -> Decimal:
    """
    Cost in EUR of a single operator working the [start_at, end_at] window,
    priced with their effective wage and the per-day overtime multiplier.
    """
    if holiday_dates is None:
        holiday_dates = _holiday_dates_for_window(start_at, end_at)
    total = Decimal("0")
    for d, hours in hours_by_local_day(start_at, end_at).items():
        wage = pick_wage(user_id, d)
        if not wage:
            continue
        try_to_eur = fx(d)
        if try_to_eur == 0:
            continue
        base_hourly = Decimal(str(wage["base_monthly"])) / WAGE_MONTH_HOURS
        mult = overtime_multiplier(classify_overtime_day(d, holiday_dates), wage)
        total += hours * base_hourly * mult * try_to_eur
    return total


def compute_request_cost_impact(request, *, only_approved: bool = False) -> dict:
    """
    Group the request's entries by job_no and, for each distinct job, report the
    current profit and the profit after this overtime is added, plus the total
    overtime cost across all jobs.

    ``only_approved`` restricts the calculation to entries with status='approved'
    (used after a decision); otherwise every entry that has not been rejected is
    counted.

    Rejected entries are always excluded: someone retracted during partial
    approval does not work the overtime, so they cost nothing. Excluding rather
    than filtering on 'approved' matches OvertimeUsersForDateView — entries
    created before per-entry decisions existed still carry the default
    status='pending' and must keep counting.
    """
    # Local import avoids a hard dependency at module import time.
    from projects.models import JobOrder
    from projects.services.costing import build_job_cost_payload

    entries = [e for e in request.entries.all() if e.status != "rejected"]
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
            "customer_name": None,
            "customer_code": None,
            "target_completion_date": None,
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
                JobOrder.objects.select_related("cost_summary", "customer")
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

            customer = getattr(job_order, "customer", None)
            target_date = getattr(job_order, "target_completion_date", None)

            row.update(
                {
                    "title": getattr(job_order, "title", None) or getattr(job_order, "name", None),
                    "customer_name": getattr(customer, "name", None) if customer else None,
                    "customer_code": getattr(customer, "code", None) if customer else None,
                    "target_completion_date": target_date.isoformat() if target_date else None,
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
