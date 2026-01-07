# tasks/services/costing.py
"""
Part cost calculation service.
Adapted from machining.services.costing for the Part/Operation system.
"""
from __future__ import annotations
from django.db.models import Avg
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from bisect import bisect_right

from django.db import transaction
from django.contrib.contenttypes.models import ContentType

from users.models import WageRate
from tasks.models import Part, Operation, PartCostAgg, PartCostAggUser, Timer
from machining.services.timers import split_timer_by_local_day_and_bucket
from machining.fx_utils import build_fx_lookup


WAGE_MONTH_HOURS = 225


def _build_wage_picker(user_ids):
    """
    Builds a function to pick the correct wage for a user on a given date.
    Includes system-wide average as fallback.
    Copied from machining.services.costing.
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
            return average_wages_by_currency.get('TRY')

        idx_before = bisect_right(by_user_dates[uid], d) - 1
        wage_before = lst[idx_before] if idx_before >= 0 else None

        if wage_before:
            return wage_before

        return lst[0]

    return pick


@transaction.atomic
def recompute_part_cost_snapshot(part_key: str):
    """
    Recomputes cost aggregates for a Part based on all timers across all its operations.

    This function:
    1. Collects all timers from all operations on the part
    2. Calculates hours and costs by work type (ww/ah/su)
    3. Updates PartCostAgg and PartCostAggUser tables

    Args:
        part_key: The primary key of the Part to recompute costs for
    """
    operation_content_type = ContentType.objects.get_for_model(Operation)

    # Get the part
    try:
        part = Part.objects.get(key=part_key)
    except Part.DoesNotExist:
        # Part doesn't exist, clean up any cost records
        PartCostAgg.objects.filter(part_id=part_key).delete()
        PartCostAggUser.objects.filter(part_id=part_key).delete()
        return

    # Get all operations for this part
    operation_keys = list(part.operations.values_list('key', flat=True))

    if not operation_keys:
        # No operations, clean up cost records
        PartCostAgg.objects.filter(part_id=part_key).delete()
        PartCostAggUser.objects.filter(part_id=part_key).delete()
        return

    # Get all timers across all operations
    timers = list(
        Timer.objects.select_related("user")
        .filter(
            content_type=operation_content_type,
            object_id__in=operation_keys,
            finish_time__isnull=False
        )
    )

    # Wipe existing cost records
    PartCostAgg.objects.filter(part_id=part_key).delete()
    PartCostAggUser.objects.filter(part_id=part_key).delete()

    if not timers:
        return

    job_no_label = part.job_no or ""

    user_ids = {t.user_id for t in timers}
    pick_wage = _build_wage_picker(user_ids)
    fx = build_fx_lookup("EUR")

    per_user = defaultdict(lambda: {
        "h_ww": Decimal("0"), "h_ah": Decimal("0"), "h_su": Decimal("0"),
        "c_ww": Decimal("0"), "c_ah": Decimal("0"), "c_su": Decimal("0"),
    })

    for t in timers:
        segs = split_timer_by_local_day_and_bucket(
            int(t.start_time),
            int(t.finish_time),
            tz="Europe/Istanbul"
        )
        for s in segs:
            d = s["date"]
            bucket = s["bucket"]
            hrs = Decimal(s["seconds"]) / Decimal(3600)

            wage = pick_wage(t.user_id, d)
            if not wage:
                continue

            base_monthly = Decimal(wage["base_monthly"])
            base_hourly = (base_monthly / WAGE_MONTH_HOURS)

            ah_mul = Decimal(wage["after_hours_multiplier"])
            su_mul = Decimal(wage["sunday_multiplier"])

            try_to_eur = fx(d)
            if try_to_eur == 0:
                continue

            if bucket == "weekday_work":
                c_try = hrs * base_hourly
                per_user[t.user_id]["h_ww"] += hrs
                per_user[t.user_id]["c_ww"] += (c_try * try_to_eur)
            elif bucket == "after_hours":
                c_try = hrs * base_hourly * ah_mul
                per_user[t.user_id]["h_ah"] += hrs
                per_user[t.user_id]["c_ah"] += (c_try * try_to_eur)
            else:  # sunday
                c_try = hrs * base_hourly * su_mul
                per_user[t.user_id]["h_su"] += hrs
                per_user[t.user_id]["c_su"] += (c_try * try_to_eur)

    # Finalize, quantize at write time
    q2 = lambda x: x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    tot_h_ww = sum((v["h_ww"] for v in per_user.values()), Decimal("0"))
    tot_h_ah = sum((v["h_ah"] for v in per_user.values()), Decimal("0"))
    tot_h_su = sum((v["h_su"] for v in per_user.values()), Decimal("0"))
    tot_c_ww = sum((v["c_ww"] for v in per_user.values()), Decimal("0"))
    tot_c_ah = sum((v["c_ah"] for v in per_user.values()), Decimal("0"))
    tot_c_su = sum((v["c_su"] for v in per_user.values()), Decimal("0"))
    total_cost = q2(tot_c_ww + tot_c_ah + tot_c_su)

    # Create aggregate record
    PartCostAgg.objects.create(
        part_id=part_key,
        job_no_cached=job_no_label,
        currency="EUR",
        hours_ww=q2(tot_h_ww), hours_ah=q2(tot_h_ah), hours_su=q2(tot_h_su),
        cost_ww=q2(tot_c_ww), cost_ah=q2(tot_c_ah), cost_su=q2(tot_c_su),
        total_cost=total_cost,
    )

    # Create per-user records
    for uid, v in per_user.items():
        u_tot = q2(v["c_ww"] + v["c_ah"] + v["c_su"])
        PartCostAggUser.objects.create(
            part_id=part_key,
            user_id=uid,
            job_no_cached=job_no_label,
            currency="EUR",
            hours_ww=q2(v["h_ww"]), hours_ah=q2(v["h_ah"]), hours_su=q2(v["h_su"]),
            cost_ww=q2(v["c_ww"]), cost_ah=q2(v["c_ah"]), cost_su=q2(v["c_su"]),
            total_cost=u_tot,
        )
