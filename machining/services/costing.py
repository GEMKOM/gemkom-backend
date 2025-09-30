# machining/services/costing.py
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from bisect import bisect_right

from django.db import transaction

from django.contrib.auth.models import User
from users.models import WageRate
from machining.models import JobCostAgg, JobCostAggUser
from machining.services.timers import split_timer_by_local_day_and_bucket
from machining.fx_utils import build_fx_lookup
from machining.models import Task, Timer  # adjust if Timer lives elsewhere


WAGE_MONTH_HOURS = 225

def _build_wage_picker(user_ids):
    rows = (
        WageRate.objects
        .filter(user_id__in=user_ids)
        .order_by("user_id", "effective_from")
        .values("user_id","effective_from","currency","base_monthly","after_hours_multiplier","sunday_multiplier")
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
            return None
        idx = bisect_right(by_user_dates[uid], d) - 1
        return lst[idx] if idx >= 0 else None

    return pick

@transaction.atomic
def recompute_job_cost_snapshot(job_no: str):
    timers = (
        Timer.objects
        .select_related("user", "issue_key")
        .filter(issue_key__job_no=job_no, finish_time__isnull=False)
    )
    timers = list(timers)
    # wipe aggregates if no timers
    if not timers:
        JobCostAgg.objects.filter(job_no=job_no).delete()
        JobCostAggUser.objects.filter(job_no=job_no).delete()
        return

    user_ids = {t.user_id for t in timers}
    pick_wage = _build_wage_picker(user_ids)
    fx = build_fx_lookup("EUR")

    per_user = defaultdict(lambda: {
        "h_ww": Decimal("0"), "h_ah": Decimal("0"), "h_su": Decimal("0"),
        "c_ww": Decimal("0"), "c_ah": Decimal("0"), "c_su": Decimal("0"),
    })

    for t in timers:
        segs = split_timer_by_local_day_and_bucket(int(t.start_time), int(t.finish_time), tz="Europe/Istanbul")
        for s in segs:
            d = s["date"]
            bucket = s["bucket"]
            hrs = Decimal(s["seconds"]) / Decimal(3600)

            wage = pick_wage(t.user_id, d)
            if not wage:
                # >>> CHANGE: if no wage for THIS USER on THIS DATE → ignore both hours & cost
                continue

            # >>> CHANGE: monthly → hourly
            base_monthly = Decimal(wage["base_monthly"])
            base_hourly  = (base_monthly / WAGE_MONTH_HOURS)  # precise Decimal division

            ah_mul = Decimal(wage["after_hours_multiplier"])
            su_mul = Decimal(wage["sunday_multiplier"])

            try_to_eur = fx(d)
            if try_to_eur == 0:
                # no FX rate → skip this segment (or log)
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

    # finalize, quantize at write time
    q2 = lambda x: x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    tot_h_ww = sum((v["h_ww"] for v in per_user.values()), Decimal("0"))
    tot_h_ah = sum((v["h_ah"] for v in per_user.values()), Decimal("0"))
    tot_h_su = sum((v["h_su"] for v in per_user.values()), Decimal("0"))
    tot_c_ww = sum((v["c_ww"] for v in per_user.values()), Decimal("0"))
    tot_c_ah = sum((v["c_ah"] for v in per_user.values()), Decimal("0"))
    tot_c_su = sum((v["c_su"] for v in per_user.values()), Decimal("0"))
    total_cost = q2(tot_c_ww + tot_c_ah + tot_c_su)

    JobCostAgg.objects.filter(job_no=job_no).delete()
    JobCostAggUser.objects.filter(job_no=job_no).delete()

    JobCostAgg.objects.create(
        job_no=job_no, currency="EUR",
        hours_ww=q2(tot_h_ww), hours_ah=q2(tot_h_ah), hours_su=q2(tot_h_su),
        cost_ww=q2(tot_c_ww),  cost_ah=q2(tot_c_ah),  cost_su=q2(tot_c_su),
        total_cost=total_cost,
    )

    # per-user rows (optional table)
    for uid, v in per_user.items():
        u_tot = q2(v["c_ww"] + v["c_ah"] + v["c_su"])
        JobCostAggUser.objects.create(
            job_no=job_no, user_id=uid, currency="EUR",
            hours_ww=q2(v["h_ww"]), hours_ah=q2(v["h_ah"]), hours_su=q2(v["h_su"]),
            cost_ww=q2(v["c_ww"]),  cost_ah=q2(v["c_ah"]),  cost_su=q2(v["c_su"]),
            total_cost=u_tot,
        )
