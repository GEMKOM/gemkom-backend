# overtime/services/cost_report.py
"""
Period overtime cost report.

Answers "what did overtime cost us between date X and date Y?", broken down by
team, person and job, with a per-request drill-down.

Pricing reuses exactly the same machinery as ``overtime.services.cost`` (the
per-request cost-impact popup approvers already see), so the numbers here and
there agree:
    wage   = users.WageRate effective on the day
    hourly = base_monthly / WAGE_MONTH_HOURS
    cost   = hours * hourly * overtime_multiplier(day) * TRY->EUR(day)

Rates are per calendar day, never per time-of-day: weekday 1.5x, Saturday 1.5x,
Sunday 2x, public holiday 2x. Overtime is worked outside normal hours by
definition, so no hour is ever charged at 1x. Saturday/weekday and
Sunday/holiday share a rate but stay separate buckets so they report apart.

Two things this adds on top of ``cost.py``:

1. **Period clipping.** A request that straddles the period boundary is charged
   only for the part of its window that falls inside [start_date, end_date].
   Without this, running the report month by month would double-count any
   overtime block that crosses midnight on the 1st.

2. **Honesty flags.** ``_build_wage_picker`` silently falls back to a
   system-wide average (and ultimately to a 1.0 TRY placeholder) for users with
   no WageRate row, and segments with no FX snapshot are skipped entirely. Both
   would otherwise show up as "cheap overtime" with no indication that the
   figure is not real. The report counts them and surfaces them.

Read-only — nothing here writes to the DB.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.db.models import Prefetch

from machining.fx_utils import build_fx_lookup
from tasks.services.costing import _build_wage_picker, WAGE_MONTH_HOURS

from ..models import OvertimeEntry, OvertimeRequest
from .cost import (
    OVERTIME_BUCKETS,
    classify_overtime_day,
    hours_by_local_day,
    overtime_multiplier,
)

IST = ZoneInfo("Europe/Istanbul")
_Q2 = Decimal("0.01")
_ZERO = Decimal("0")

# weekday 1.5x / saturday 1.5x / sunday 2x / holiday 2x — see overtime.services.cost.
BUCKETS = OVERTIME_BUCKETS

VALID_STATUSES = {"submitted", "approved", "rejected", "cancelled"}
DEFAULT_STATUSES = ("approved",)


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_Q2, rounding=ROUND_HALF_UP)


def _s2(value: Decimal) -> str:
    return str(_q2(value))


def parse_report_date(value, default: date) -> date:
    """Accept YYYY-MM-DD or DD.MM.YYYY; empty falls back to ``default``."""
    if not value:
        return default
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Geçersiz tarih: {value}. Beklenen biçim: YYYY-AA-GG.")


def default_period() -> tuple[date, date]:
    """Current calendar month."""
    today = datetime.now(IST).date()
    first = today.replace(day=1)
    return first, today


def _period_bounds(start_date: date, end_date: date):
    """Local-midnight aware datetimes; end is exclusive (day after end_date)."""
    start = datetime.combine(start_date, time.min, tzinfo=IST)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=IST)
    return start, end


def _holiday_dates(start_date: date, end_date: date) -> set:
    from attendance.models import PublicHoliday  # local import (app-load cycles)

    return set(
        PublicHoliday.objects
        .filter(date__gte=start_date, date__lte=end_date)
        .values_list("date", flat=True)
    )


def _empty_buckets() -> dict:
    return {b: {"hours": _ZERO, "cost": _ZERO} for b in BUCKETS}


def _add_buckets(target: dict, source: dict) -> None:
    for b in BUCKETS:
        target[b]["hours"] += source[b]["hours"]
        target[b]["cost"] += source[b]["cost"]


def _serialize_buckets(buckets: dict) -> dict:
    return {
        b: {"hours": _s2(buckets[b]["hours"]), "cost_eur": _s2(buckets[b]["cost"])}
        for b in BUCKETS
    }


def compute_window_breakdown(user_id: int, start_at, end_at, *, pick_wage, fx, holiday_dates) -> dict:
    """
    Cost of one operator working [start_at, end_at), split by day/bucket.

    Returns hours and EUR cost per bucket plus the flags described in the module
    docstring. ``start_at``/``end_at`` are expected to be already clipped to the
    reporting period by the caller.
    """
    buckets = _empty_buckets()
    total_cost = _ZERO
    total_hours = _ZERO
    unpriced_hours = _ZERO
    estimated_wage = False

    for d, hours in hours_by_local_day(start_at, end_at).items():
        total_hours += hours

        bucket = classify_overtime_day(d, holiday_dates)
        buckets[bucket]["hours"] += hours

        wage = pick_wage(user_id, d)
        if not wage:
            unpriced_hours += hours
            continue
        # _build_wage_picker returns user_id=None for its average/placeholder
        # fallbacks — i.e. this person has no WageRate of their own.
        if wage.get("user_id") is None:
            estimated_wage = True

        try_to_eur = fx(d)
        if try_to_eur == 0:
            unpriced_hours += hours
            continue

        base_hourly = Decimal(str(wage["base_monthly"])) / WAGE_MONTH_HOURS
        cost = hours * base_hourly * overtime_multiplier(bucket, wage) * try_to_eur

        buckets[bucket]["cost"] += cost
        total_cost += cost

    return {
        "hours": total_hours,
        "cost": total_cost,
        "buckets": buckets,
        "unpriced_hours": unpriced_hours,
        "estimated_wage": estimated_wage,
    }


def _new_group(**extra) -> dict:
    row = {"hours": _ZERO, "cost": _ZERO, "entry_count": 0, "request_ids": set()}
    row.update(extra)
    return row


def _finish_group(row: dict, keys: tuple) -> dict:
    out = {k: row[k] for k in keys}
    out.update({
        "hours": _s2(row["hours"]),
        "cost_eur": _s2(row["cost"]),
        "entry_count": row["entry_count"],
        "request_count": len(row["request_ids"]),
    })
    return out


def build_overtime_cost_report(
    *,
    start_date=None,
    end_date=None,
    statuses=None,
    team=None,
    user_id=None,
    job_no=None,
) -> dict:
    """
    Aggregate overtime cost over a date range.

    Requests are included when their window *overlaps* the period, and each is
    charged only for the overlapping part. Entries rejected during partial
    approval are excluded — nobody worked them, so they cost nothing.

    ``statuses`` defaults to ('approved',); pass ('approved', 'submitted') to
    include the pending pipeline as a forecast.
    """
    d_start, d_end = default_period()
    start_date = parse_report_date(start_date, d_start)
    end_date = parse_report_date(end_date, d_end)
    if end_date < start_date:
        raise ValueError("Bitiş tarihi başlangıç tarihinden önce olamaz.")

    statuses = tuple(statuses) if statuses else DEFAULT_STATUSES
    invalid = set(statuses) - VALID_STATUSES
    if invalid:
        raise ValueError(f"Geçersiz durum: {sorted(invalid)}")

    period_start, period_end = _period_bounds(start_date, end_date)

    requests = (
        OvertimeRequest.objects
        .filter(status__in=statuses, start_at__lt=period_end, end_at__gt=period_start)
        .select_related("requester")
        .prefetch_related(
            Prefetch(
                "entries",
                queryset=OvertimeEntry.objects.exclude(status="rejected").select_related("user"),
            )
        )
        .order_by("start_at", "id")
    )
    if team:
        requests = requests.filter(team=team)
    if user_id:
        requests = requests.filter(entries__user_id=user_id).distinct()
    if job_no:
        requests = requests.filter(entries__job_no=job_no).distinct()

    requests = list(requests)

    entry_user_ids = {e.user_id for r in requests for e in r.entries.all()}
    pick_wage = _build_wage_picker(entry_user_ids)
    fx = build_fx_lookup("EUR")
    holiday_dates = _holiday_dates(start_date, end_date)

    total_cost = _ZERO
    total_hours = _ZERO
    total_unpriced_hours = _ZERO
    estimated_entry_count = 0
    entry_count = 0
    total_buckets = _empty_buckets()

    by_team: "OrderedDict[str, dict]" = OrderedDict()
    by_user: "OrderedDict[int, dict]" = OrderedDict()
    by_job: "OrderedDict[str, dict]" = OrderedDict()
    request_rows = []

    for req in requests:
        # Charge only the slice of this request that falls inside the period.
        win_start = max(req.start_at, period_start)
        win_end = min(req.end_at, period_end)
        if win_end <= win_start:
            continue

        entries = list(req.entries.all())
        if user_id:
            entries = [e for e in entries if e.user_id == int(user_id)]
        if job_no:
            entries = [e for e in entries if (e.job_no or "") == job_no]
        if not entries:
            continue

        req_cost = _ZERO
        req_hours = _ZERO
        req_buckets = _empty_buckets()
        entry_rows = []

        for e in entries:
            bd = compute_window_breakdown(
                e.user_id, win_start, win_end,
                pick_wage=pick_wage, fx=fx, holiday_dates=holiday_dates,
            )

            entry_count += 1
            total_cost += bd["cost"]
            total_hours += bd["hours"]
            total_unpriced_hours += bd["unpriced_hours"]
            if bd["estimated_wage"]:
                estimated_entry_count += 1
            _add_buckets(total_buckets, bd["buckets"])

            req_cost += bd["cost"]
            req_hours += bd["hours"]
            _add_buckets(req_buckets, bd["buckets"])

            team_key = req.team or ""
            t = by_team.setdefault(team_key, _new_group(team=team_key))
            t["hours"] += bd["hours"]; t["cost"] += bd["cost"]
            t["entry_count"] += 1; t["request_ids"].add(req.id)

            full_name = e.user.get_full_name() or e.user.username
            u = by_user.setdefault(
                e.user_id,
                _new_group(user_id=e.user_id, username=e.user.username,
                           full_name=full_name, estimated_wage=False),
            )
            u["hours"] += bd["hours"]; u["cost"] += bd["cost"]
            u["entry_count"] += 1; u["request_ids"].add(req.id)
            u["estimated_wage"] = u["estimated_wage"] or bd["estimated_wage"]

            job_key = (e.job_no or "").strip()
            j = by_job.setdefault(job_key, _new_group(job_no=job_key))
            j["hours"] += bd["hours"]; j["cost"] += bd["cost"]
            j["entry_count"] += 1; j["request_ids"].add(req.id)

            entry_rows.append({
                "id": e.id,
                "user_id": e.user_id,
                "username": e.user.username,
                "full_name": full_name,
                "job_no": e.job_no,
                "description": e.description,
                "status": e.status,
                "hours": _s2(bd["hours"]),
                "cost_eur": _s2(bd["cost"]),
                "estimated_wage": bd["estimated_wage"],
                "unpriced_hours": _s2(bd["unpriced_hours"]),
                "buckets": _serialize_buckets(bd["buckets"]),
            })

        request_rows.append({
            "id": req.id,
            "status": req.status,
            "team": req.team,
            "reason": req.reason,
            "requester_id": req.requester_id,
            "requester_name": req.requester.get_full_name() or req.requester.username,
            "start_at": req.start_at.isoformat(),
            "end_at": req.end_at.isoformat(),
            "duration_hours": str(req.duration_hours),
            # Differs from start_at/end_at only when the request straddles a
            # period edge — the frontend flags those rows as partially counted.
            "counted_start_at": win_start.isoformat(),
            "counted_end_at": win_end.isoformat(),
            "is_partial": (win_start != req.start_at or win_end != req.end_at),
            "entry_count": len(entry_rows),
            "hours": _s2(req_hours),
            "cost_eur": _s2(req_cost),
            "buckets": _serialize_buckets(req_buckets),
            "entries": entry_rows,
        })

    team_rows = sorted(
        (_finish_group(r, ("team",)) for r in by_team.values()),
        key=lambda r: Decimal(r["cost_eur"]), reverse=True,
    )
    user_rows = sorted(
        (_finish_group(r, ("user_id", "username", "full_name", "estimated_wage"))
         for r in by_user.values()),
        key=lambda r: Decimal(r["cost_eur"]), reverse=True,
    )
    job_rows = sorted(
        (_finish_group(r, ("job_no",)) for r in by_job.values()),
        key=lambda r: Decimal(r["cost_eur"]), reverse=True,
    )

    return {
        "meta": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "currency": "EUR",
            "statuses": list(statuses),
            "team": team or None,
            "user": int(user_id) if user_id else None,
            "job_no": job_no or None,
        },
        "summary": {
            "total_cost_eur": _s2(total_cost),
            "total_hours": _s2(total_hours),
            "request_count": len(request_rows),
            "entry_count": entry_count,
            "user_count": len(by_user),
            "job_count": len(by_job),
            "avg_cost_per_hour_eur": _s2(total_cost / total_hours) if total_hours > 0 else "0.00",
            # Data-quality flags — see module docstring.
            "estimated_wage_entry_count": estimated_entry_count,
            "unpriced_hours": _s2(total_unpriced_hours),
        },
        "by_bucket": _serialize_buckets(total_buckets),
        "by_team": team_rows,
        "by_user": user_rows,
        "by_job": job_rows,
        "requests": request_rows,
    }
