# welding/services/costing.py
from __future__ import annotations
from django.db.models import Avg
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from bisect import bisect_right

from django.db import transaction
from django.contrib.auth.models import User
from users.models import WageRate
from welding.models import WeldingJobCostAgg, WeldingJobCostAggUser, WeldingTimeEntry
from machining.fx_utils import build_fx_lookup

WAGE_MONTH_HOURS = 225


def _build_wage_picker(user_ids):
    """
    Build a function that picks the appropriate wage rate for a user on a given date.
    Falls back to system-wide average if user has no wage rates.
    """
    # Calculate system-wide average wages per currency
    all_wages_avg = (
        WageRate.objects
        .values('currency')
        .annotate(
            avg_base_monthly=Avg('base_monthly'),
            avg_ah_multiplier=Avg('after_hours_multiplier'),
            avg_su_multiplier=Avg('sunday_multiplier')
        )
    )

    average_wages_by_currency = {}
    for avg_data in all_wages_avg:
        currency = avg_data['currency']
        average_wages_by_currency[currency] = {
            "user_id": None,
            "effective_from": date(1970, 1, 1),
            "currency": currency,
            "base_monthly": avg_data['avg_base_monthly'] or Decimal('0'),
            "after_hours_multiplier": avg_data['avg_ah_multiplier'] or Decimal('1.5'),
            "sunday_multiplier": avg_data['avg_su_multiplier'] or Decimal('2.0'),
        }

    # Create a "last resort" default wage if no averages exist
    if 'TRY' not in average_wages_by_currency:
        average_wages_by_currency['TRY'] = {
            "user_id": None,
            "effective_from": date(1970, 1, 1),
            "currency": "TRY",
            "base_monthly": Decimal('1.0'),
            "after_hours_multiplier": Decimal('1.5'),
            "sunday_multiplier": Decimal('2.0'),
        }

    rows = (
        WageRate.objects
        .filter(user_id__in=user_ids)
        .order_by("user_id", "effective_from")
        .values("user_id", "effective_from", "currency", "base_monthly", "after_hours_multiplier", "sunday_multiplier")
    )
    by_user = defaultdict(list)
    by_user_dates = {}
    for r in rows:
        by_user[r["user_id"]].append(r)
    for uid, lst in by_user.items():
        by_user_dates[uid] = [x["effective_from"] for x in lst]

    def pick(uid: int, d: date):
        lst = by_user.get(uid)
        if not lst:
            # Fallback to system-wide average for TRY
            return average_wages_by_currency.get('TRY')

        # Find the wage rate effective on or before the given date
        idx_before = bisect_right(by_user_dates[uid], d) - 1
        wage_before = lst[idx_before] if idx_before >= 0 else None

        if wage_before:
            return wage_before

        # If no rate is found before the date, return the earliest one
        return lst[0]

    return pick


@transaction.atomic
def recompute_welding_job_cost(job_no: str):
    """
    Recompute cost aggregations for a specific welding job.

    This reads all WeldingTimeEntry records for the given job_no,
    calculates costs based on employee wage rates and overtime multipliers,
    and updates WeldingJobCostAgg and WeldingJobCostAggUser tables.

    Cost calculation:
    - regular: base_hourly * hours
    - after_hours: base_hourly * hours * 1.5
    - holiday: base_hourly * hours * 2.0

    All costs are converted to EUR using historical exchange rates.
    """
    entries = (
        WeldingTimeEntry.objects
        .filter(job_no=job_no)
        .select_related('employee')
        .order_by('date')
    )
    entries = list(entries)

    # Wipe existing aggregations for this job
    WeldingJobCostAgg.objects.filter(job_no=job_no).delete()
    WeldingJobCostAggUser.objects.filter(job_no=job_no).delete()

    if not entries:
        return

    user_ids = {e.employee_id for e in entries}
    pick_wage = _build_wage_picker(user_ids)
    fx = build_fx_lookup("EUR")

    # Per-user accumulator
    # Keys: h_reg, h_ah, h_hol, c_reg, c_ah, c_hol
    per_user = defaultdict(lambda: {
        "h_reg": Decimal("0"), "h_ah": Decimal("0"), "h_hol": Decimal("0"),
        "c_reg": Decimal("0"), "c_ah": Decimal("0"), "c_hol": Decimal("0"),
    })

    for entry in entries:
        d = entry.date
        hrs = Decimal(str(entry.hours))
        overtime_type = entry.overtime_type
        uid = entry.employee_id

        wage = pick_wage(uid, d)
        if not wage:
            continue

        # Calculate hourly rate
        base_monthly = Decimal(wage["base_monthly"])
        base_hourly = base_monthly / WAGE_MONTH_HOURS

        ah_mul = Decimal(wage["after_hours_multiplier"])
        su_mul = Decimal(wage["sunday_multiplier"])

        # Get FX rate for the date (TRY to EUR)
        try_to_eur = fx(d)
        if try_to_eur == 0:
            # No FX rate → skip this entry (or log)
            continue

        # Calculate cost based on overtime type
        if overtime_type == "regular":
            c_try = hrs * base_hourly
            per_user[uid]["h_reg"] += hrs
            per_user[uid]["c_reg"] += (c_try * try_to_eur)
        elif overtime_type == "after_hours":
            c_try = hrs * base_hourly * ah_mul
            per_user[uid]["h_ah"] += hrs
            per_user[uid]["c_ah"] += (c_try * try_to_eur)
        else:  # holiday
            c_try = hrs * base_hourly * su_mul
            per_user[uid]["h_hol"] += hrs
            per_user[uid]["c_hol"] += (c_try * try_to_eur)

    # Quantize helper
    q2 = lambda x: x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Calculate totals across all users
    tot_h_reg = sum((v["h_reg"] for v in per_user.values()), Decimal("0"))
    tot_h_ah = sum((v["h_ah"] for v in per_user.values()), Decimal("0"))
    tot_h_hol = sum((v["h_hol"] for v in per_user.values()), Decimal("0"))
    tot_c_reg = sum((v["c_reg"] for v in per_user.values()), Decimal("0"))
    tot_c_ah = sum((v["c_ah"] for v in per_user.values()), Decimal("0"))
    tot_c_hol = sum((v["c_hol"] for v in per_user.values()), Decimal("0"))
    total_cost = q2(tot_c_reg + tot_c_ah + tot_c_hol)

    # Create job-level aggregation
    WeldingJobCostAgg.objects.create(
        job_no=job_no,
        currency="EUR",
        hours_regular=q2(tot_h_reg),
        hours_after_hours=q2(tot_h_ah),
        hours_holiday=q2(tot_h_hol),
        cost_regular=q2(tot_c_reg),
        cost_after_hours=q2(tot_c_ah),
        cost_holiday=q2(tot_c_hol),
        total_cost=total_cost,
    )

    # Create per-user aggregations
    for uid, v in per_user.items():
        u_tot = q2(v["c_reg"] + v["c_ah"] + v["c_hol"])
        WeldingJobCostAggUser.objects.create(
            job_no=job_no,
            user_id=uid,
            currency="EUR",
            hours_regular=q2(v["h_reg"]),
            hours_after_hours=q2(v["h_ah"]),
            hours_holiday=q2(v["h_hol"]),
            cost_regular=q2(v["c_reg"]),
            cost_after_hours=q2(v["c_ah"]),
            cost_holiday=q2(v["c_hol"]),
            total_cost=u_tot,
        )
