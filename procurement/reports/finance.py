# procurement/reports/executive.py
from __future__ import annotations
from decimal import Decimal
from collections import defaultdict
from django.db.models import Q
from django.utils import timezone
from ..models import PurchaseOrder
from .common import q2, extract_rates, get_fallback_rates, to_eur

# procurement/reports/cash_forecast.py

from decimal import Decimal
from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from ..models import PurchaseOrder, PaymentSchedule
from .common import q2, extract_rates, get_fallback_rates, to_eur

# procurement/reports/concentration.py

from decimal import Decimal
from django.db.models import Q
from ..models import PurchaseOrder
from .common import q2, extract_rates, get_fallback_rates, to_eur

# procurement/reports/cycle_time.py

from decimal import Decimal
from statistics import median
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from ..models import PurchaseRequest, PurchaseOrder

# procurement/reports/price_variance.py

from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from ..models import PurchaseOrderLine, Item
from .common import q2, extract_rates, get_fallback_rates, to_eur

# procurement/reports/projects.py

from decimal import Decimal
from collections import defaultdict, Counter
from django.db.models import Q
from django.utils import timezone
from ..models import (
    PurchaseOrder, PurchaseOrderLine, PurchaseOrderLineAllocation,
    PurchaseRequestItemAllocation, PurchaseRequestItem, ItemOffer, Supplier
)
from .common import q2, extract_rates, get_fallback_rates, to_eur

def _month_key(dt):  # YYYY-MM
    dt = dt or timezone.now()
    return f"{dt.year:04d}-{dt.month:02d}"

def build_executive_overview(request):
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")

    qs = PurchaseOrder.objects.exclude(status="cancelled").select_related("pr", "supplier")
    if created_gte:
        qs = qs.filter(Q(created_at__gte=created_gte) | Q(ordered_at__gte=created_gte))
    if created_lte:
        qs = qs.filter(Q(created_at__lte=created_lte) | Q(ordered_at__lte=created_lte))

    fb = get_fallback_rates()

    # Series by month
    by_month = defaultdict(lambda: {
        "total_spent_eur": Decimal("0.00"),
        "total_tax_eur": Decimal("0.00"),
        "po_count": 0,
        "active_suppliers": set(),
    })

    total_spent = Decimal("0.00")
    total_tax   = Decimal("0.00")
    suppliers_all = set()

    for po in qs:
        ts = po.ordered_at or po.created_at
        mk = _month_key(ts)
        pr_rates = extract_rates(po.pr.currency_rates_snapshot or {})
        net = to_eur(po.total_amount, po.currency or "TRY", pr_rates, fb) or Decimal("0.00")
        tax = to_eur(po.total_tax_amount, po.currency or "TRY", pr_rates, fb) or Decimal("0.00")

        by_month[mk]["total_spent_eur"] += net
        by_month[mk]["total_tax_eur"] += tax
        by_month[mk]["po_count"] += 1
        if po.supplier_id:
            by_month[mk]["active_suppliers"].add(po.supplier_id)
            suppliers_all.add(po.supplier_id)

        total_spent += net
        total_tax += tax

    # build series + compute MoM/YoY based on latest month we have
    months = sorted(by_month.keys())
    series = []
    for m in months:
        row = by_month[m]
        series.append({
            "month": m,
            "total_spent_eur": str(q2(row["total_spent_eur"])),
            "total_gross_eur": str(q2(row["total_spent_eur"] + row["total_tax_eur"])),
            "po_count": row["po_count"],
            "active_suppliers": len(row["active_suppliers"]),
        })

    # KPI cards
    latest = months[-1] if months else None
    mom = yoy = None
    if latest:
        # previous month key
        yyyy, mm = map(int, latest.split("-"))
        prev_m = f"{(yyyy if mm>1 else yyyy-1):04d}-{(mm-1 if mm>1 else 12):02d}"
        last_year = f"{yyyy-1:04d}-{mm:02d}"
        cur_val = by_month[latest]["total_spent_eur"]
        if prev_m in by_month and by_month[prev_m]["total_spent_eur"] > 0:
            base = by_month[prev_m]["total_spent_eur"]
            mom = float((cur_val - base) / base) * 100.0
        if last_year in by_month and by_month[last_year]["total_spent_eur"] > 0:
            base = by_month[last_year]["total_spent_eur"]
            yoy = float((cur_val - base) / base) * 100.0

    kpis = {
        "total_spent_eur": str(q2(total_spent)),
        "total_gross_eur": str(q2(total_spent + total_tax)),
        "po_count": sum(r["po_count"] for r in by_month.values()),
        "active_suppliers": len(suppliers_all),
        "mom_percent": (round(mom, 2) if mom is not None else None),
        "yoy_percent": (round(yoy, 2) if yoy is not None else None),
    }
    return {"kpis": kpis, "series": series}


def build_concentration_report(request):
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")
    top_n = int(request.query_params.get("top_n", 10))
    tail_threshold_pct = Decimal(str(request.query_params.get("tail_threshold_pct", "1")))

    qs = PurchaseOrder.objects.exclude(status="cancelled").select_related("pr", "supplier")
    if created_gte:
        qs = qs.filter(Q(created_at__gte=created_gte) | Q(ordered_at__gte=created_gte))
    if created_lte:
        qs = qs.filter(Q(created_at__lte=created_lte) | Q(ordered_at__lte=created_lte))

    fb = get_fallback_rates()
    by_sup = {}
    total = Decimal("0.00")

    for po in qs:
        if not po.supplier_id:
            continue
        pr_rates = extract_rates(po.pr.currency_rates_snapshot or {})
        net = to_eur(po.total_amount, po.currency or "TRY", pr_rates, fb) or Decimal("0.00")
        by_sup.setdefault(po.supplier_id, {"name": po.supplier.name, "total": Decimal("0.00")})
        by_sup[po.supplier_id]["total"] += net
        total += net

    ranking = sorted(
        [{"supplier_id": s, "name": v["name"], "total_eur": v["total"]} for s, v in by_sup.items()],
        key=lambda x: x["total_eur"], reverse=True
    )
    for r in ranking:
        r["share_pct"] = float((r["total_eur"] / total) * 100) if total > 0 else 0.0
        r["total_eur"] = str(q2(r["total_eur"]))
        r["share_pct"] = round(r["share_pct"], 2)

    # HHI: sum of squared shares (in decimals)
    hhi = float(sum((float(row["share_pct"]) / 100.0) ** 2 for row in ranking))
    hhi = round(hhi, 4)

    # Tail spend share: suppliers below threshold pct
    tail_share = float(sum((float(r["share_pct"]) for r in ranking if Decimal(str(r["share_pct"])) < tail_threshold_pct)))  # already %
    tail_share = round(tail_share, 2)

    return {
        "kpis": {
            "total_spend_eur": str(q2(total)),
            "hhi": hhi,
            "tail_share_pct": tail_share,
            "top_n": top_n
        },
        "top": ranking[:top_n],
        "distribution_count": len(ranking)
    }

def build_cash_forecast(request):
    today = timezone.now().date()
    horizon_weeks = int(request.query_params.get("weeks", 12))
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")

    # unpaid schedules only, join PO/PR for FX + status (exclude cancelled)
    sch_qs = (
        PaymentSchedule.objects
        .select_related("purchase_order__pr", "purchase_order__supplier")
        .filter(is_paid=False)
        .exclude(purchase_order__status="cancelled")
    )
    if created_gte:
        sch_qs = sch_qs.filter(Q(purchase_order__created_at__gte=created_gte) | Q(purchase_order__ordered_at__gte=created_gte))
    if created_lte:
        sch_qs = sch_qs.filter(Q(purchase_order__created_at__lte=created_lte) | Q(purchase_order__ordered_at__lte=created_lte))

    fb = get_fallback_rates()
    buckets = {
        "overdue": Decimal("0.00"),
        "due_0_30": Decimal("0.00"),
        "due_31_60": Decimal("0.00"),
        "due_61_90": Decimal("0.00"),
        "due_90_plus": Decimal("0.00"),
    }
    series_weeks = []  # next N weeks
    week_lines = defaultdict(Decimal)

    for sch in sch_qs:
        po = sch.purchase_order
        pr_rates = extract_rates(po.pr.currency_rates_snapshot or {})
        amt_eur = to_eur(sch.amount, sch.currency or po.currency or "TRY", pr_rates, fb)
        if amt_eur is None:
            continue

        due = sch.due_date or today
        delta = (due - today).days

        if delta < 0:
            buckets["overdue"] += amt_eur
        elif delta <= 30:
            buckets["due_0_30"] += amt_eur
        elif delta <= 60:
            buckets["due_31_60"] += amt_eur
        elif delta <= 90:
            buckets["due_61_90"] += amt_eur
        else:
            buckets["due_90_plus"] += amt_eur

        # weekly
        start_of_week = due - timedelta(days=due.weekday())  # Monday anchor
        week_lines[start_of_week] += amt_eur

    # build weekly series
    for i in range(horizon_weeks):
        wk = today + timedelta(days=(7 * i))
        monday = wk - timedelta(days=wk.weekday())
        series_weeks.append({
            "week_start": str(monday),
            "unpaid_eur": str(q2(week_lines[monday])),
        })

    return {
        "buckets": {k: str(q2(v)) for k, v in buckets.items()},
        "weekly": series_weeks
    }

def _percentile(sorted_vals, p):  # p in [0,100]
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals)-1, int(round((p/100.0)*(len(sorted_vals)-1)))))
    return sorted_vals[k]

def build_cycle_time_report(request):
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")

    prs = PurchaseRequest.objects.all()
    if created_gte: prs = prs.filter(created_at__gte=created_gte)
    if created_lte: prs = prs.filter(created_at__lte=created_lte)

    # PR→PO conversion (exclude cancelled POs)
    po_exists = PurchaseOrder.objects.filter(pr=OuterRef("pk")).exclude(status="cancelled")
    prs = prs.annotate(has_po=Exists(po_exists))

    # Collect cycle times in days
    cycles = []
    pr_total = 0
    pr_with_po = 0

    for pr in prs:
        pr_total += 1
        if pr.has_po:
            pr_with_po += 1
            # take earliest PO for cycle time, or earliest ordered_at/created_at
            pos = (PurchaseOrder.objects.filter(pr=pr).exclude(status="cancelled")
                   .order_by("ordered_at", "created_at").only("ordered_at","created_at"))
            po0 = pos.first()
            if po0:
                po_ts = po0.ordered_at or po0.created_at
                pr_ts = pr.created_at
                if po_ts and pr_ts:
                    days = (po_ts - pr_ts).days
                    if days >= 0:
                        cycles.append(days)

    cycles_sorted = sorted(cycles)
    med = median(cycles_sorted) if cycles_sorted else None
    p90 = _percentile(cycles_sorted, 90)
    p95 = _percentile(cycles_sorted, 95)
    avg = (sum(cycles_sorted)/len(cycles_sorted)) if cycles_sorted else None

    return {
        "kpis": {
            "pr_total": pr_total,
            "po_from_pr": pr_with_po,
            "conversion_rate_pct": (round((pr_with_po/pr_total)*100.0,2) if pr_total else 0.0),
            "cycle_days_median": med,
            "cycle_days_p90": p90,
            "cycle_days_p95": p95,
            "cycle_days_avg": (round(avg,2) if avg is not None else None),
        },
        "distribution": cycles_sorted[:5000]  # cap to avoid huge payloads
    }



def build_price_variance_report(request):
    code_q = request.query_params.get("code")
    name_q = request.query_params.get("name")
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")
    ordering = (request.query_params.get("ordering") or "-ppv_vs_avg_pct").strip()

    items = Item.objects.all()
    if code_q: items = items.filter(code__icontains=code_q)
    if name_q: items = items.filter(name__icontains=name_q)

    fb = get_fallback_rates()
    rows = []

    for it in items:
        lines = (
            PurchaseOrderLine.objects
            .select_related("po", "po__pr")
            .exclude(po__status="cancelled")
            .filter(purchase_request_item__item=it)
        )
        if created_gte:
            lines = lines.filter(Q(po__created_at__gte=created_gte) | Q(po__ordered_at__gte=created_gte))
        if created_lte:
            lines = lines.filter(Q(po__created_at__lte=created_lte) | Q(po__ordered_at__lte=created_lte))

        if not lines.exists():
            continue

        total_spent = Decimal("0.00")
        w_qty = Decimal("0.00")
        sum_unit_x_qty = Decimal("0.00")
        min_unit = None
        last_unit = None
        last_ts = None

        for ln in lines:
            pr_rates = extract_rates(ln.po.pr.currency_rates_snapshot or {})
            unit_eur = to_eur(ln.unit_price, ln.po.currency or "TRY", pr_rates, fb)
            total_eur = to_eur(ln.total_price, ln.po.currency or "TRY", pr_rates, fb)
            if unit_eur is None and total_eur is None: 
                continue
            qty = ln.quantity or Decimal("0")
            if total_eur is not None: total_spent += total_eur
            if unit_eur is not None and qty > 0:
                sum_unit_x_qty += (unit_eur * qty)
                w_qty += qty
                if (min_unit is None) or (unit_eur < min_unit): 
                    min_unit = unit_eur

            ts = ln.po.ordered_at or ln.po.created_at
            if unit_eur is not None and ts and (last_ts is None or ts > last_ts):
                last_ts = ts
                last_unit = unit_eur

        if w_qty == 0 and min_unit is None and last_unit is None and total_spent == 0:
            continue

        avg_unit = (sum_unit_x_qty / w_qty) if w_qty > 0 else None

        def pct(delta, base):
            if base is None or base == 0:
                return None
            return round(float((delta / base) * 100.0), 2)

        ppv_vs_avg = (last_unit - avg_unit) if (last_unit is not None and avg_unit is not None) else None
        ppv_vs_min = (last_unit - min_unit) if (last_unit is not None and min_unit is not None) else None

        rows.append({
            "item_id": it.id,
            "code": it.code,
            "name": it.name,
            "avg_unit_price_eur": (str(q2(avg_unit)) if avg_unit is not None else None),
            "min_unit_price_eur": (str(q2(min_unit)) if min_unit is not None else None),
            "last_unit_price_eur": (str(q2(last_unit)) if last_unit is not None else None),
            "total_spent_eur": str(q2(total_spent)),
            "ppv_vs_avg_eur": (str(q2(ppv_vs_avg)) if ppv_vs_avg is not None else None),
            "ppv_vs_avg_pct": (pct(ppv_vs_avg, avg_unit) if ppv_vs_avg is not None and avg_unit else None),
            "ppv_vs_min_eur": (str(q2(ppv_vs_min)) if ppv_vs_min is not None else None),
            "ppv_vs_min_pct": (pct(ppv_vs_min, min_unit) if ppv_vs_min is not None and min_unit else None),
            "last_purchase_at": last_ts,
            "currency": "EUR",
        })

    if ordering:
        keys = [k.strip() for k in ordering.split(",") if k.strip()]
        for k in reversed(keys):
            rev = k.startswith("-"); kk = k.lstrip("-")
            def keyer(r):
                if kk in {"ppv_vs_avg_pct","ppv_vs_min_pct"}:
                    return r[kk] if r[kk] is not None else float("-inf")
                if kk in {"avg_unit_price_eur","min_unit_price_eur","last_unit_price_eur","total_spent_eur"}:
                    return float(r[kk]) if r[kk] is not None else 0.0
                if kk == "last_purchase_at":
                    return r[kk] or timezone.datetime.min.replace(tzinfo=timezone.utc)
                if kk in {"code","name"}:
                    return r[kk] or ""
                return r.get(kk)
            rows.sort(key=keyer, reverse=rev)

    return rows

def build_projects_report(request):
    """
    Project (job_no) rollup:
      - committed_net_eur: Σ PO line allocation.amount (non-cancelled POs), EUR
      - unpaid_eur: apportioned unpaid PaymentSchedule amounts to the job by PO allocation share, EUR
      - pending_pr_estimate_eur: EUR value of remaining (not-yet-PO'd) PR allocations using recommended ItemOffer
      - forecast_eur: committed_net_eur + pending_pr_estimate_eur
      - requested_qty_by_unit / ordered_qty_by_unit (quantities by unit)
      - counts: total_pos, cancelled_pos, active_pos
      - top_suppliers_by_spend, last_activity_at
    Filters:
      ?job_no=, ?job_prefix=, ?created_gte=YYYY-MM-DD, ?created_lte=YYYY-MM-DD, ?include_empty=1
    Ordering:
      ?ordering=forecast_eur,committed_net_eur,pending_pr_estimate_eur,unpaid_eur,last_activity_at,job_no
      Default: -forecast_eur
    """
    from collections import defaultdict, Counter
    from decimal import Decimal
    from django.db.models import Q
    from django.utils import timezone

    from ..models import (
        PurchaseOrderLineAllocation,
        PurchaseRequestItemAllocation,
        ItemOffer,
        PaymentSchedule,
    )
    from .common import q2, extract_rates, get_fallback_rates, to_eur

    job_no = request.query_params.get("job_no")
    job_prefix = request.query_params.get("job_prefix")
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")
    include_empty = request.query_params.get("include_empty") in {"1", "true", "yes", "y"}

    fb = get_fallback_rates()

    # --- PR allocations (requested quantities by unit) ---
    pri_allocs = PurchaseRequestItemAllocation.objects.select_related(
        "purchase_request_item__item",
        "purchase_request_item__purchase_request",
    )
    if job_no:
        pri_allocs = pri_allocs.filter(job_no=job_no)
    if job_prefix:
        pri_allocs = pri_allocs.filter(job_no__startswith=job_prefix)
    if created_gte:
        pri_allocs = pri_allocs.filter(purchase_request_item__purchase_request__created_at__gte=created_gte)
    if created_lte:
        pri_allocs = pri_allocs.filter(purchase_request_item__purchase_request__created_at__lte=created_lte)

    proj = {}  # job_no -> agg dict
    for a in pri_allocs:
        j = a.job_no
        it = a.purchase_request_item.item if a.purchase_request_item_id else None
        unit = (getattr(it, "unit", "") or "").strip()
        row = proj.setdefault(
            j,
            {
                "job_no": j,
                "requested_qty_by_unit": defaultdict(Decimal),
                "ordered_qty_by_unit": defaultdict(Decimal),
                "distinct_items": set(),
                "total_pos": 0,
                "cancelled_pos": 0,
                "active_pos": 0,
                "committed_net_eur": Decimal("0.00"),
                "unpaid_eur": Decimal("0.00"),
                "pending_pr_estimate_eur": Decimal("0.00"),
                "top_suppliers": Counter(),
                "last_activity_at": None,
            },
        )
        if it:
            row["requested_qty_by_unit"][unit] += (a.quantity or Decimal("0"))
            row["distinct_items"].add(it.id)

    # --- PO line allocations (commitments, ordered qty, supplier mix) ---
    line_allocs = PurchaseOrderLineAllocation.objects.select_related(
        "po_line__po__pr",
        "po_line__po__supplier",
        "po_line__purchase_request_item__item",
    )
    if job_no:
        line_allocs = line_allocs.filter(job_no=job_no)
    if job_prefix:
        line_allocs = line_allocs.filter(job_no__startswith=job_prefix)
    if created_gte:
        line_allocs = line_allocs.filter(
            Q(po_line__po__created_at__gte=created_gte) | Q(po_line__po__ordered_at__gte=created_gte)
        )
    if created_lte:
        line_allocs = line_allocs.filter(
            Q(po_line__po__created_at__lte=created_lte) | Q(po_line__po__ordered_at__lte=created_lte)
        )

    # Aggregators to avoid re-querying
    po_seen_by_job = defaultdict(set)  # job -> {po_id}
    po_info = {}  # po_id -> (currency, pr_rates, status, ts, supplier_name, po_total)
    allo_sum_by_po_job = defaultdict(Decimal)  # (po_id, job_no) -> Σ allocation.amount
    ordered_qty_by_item_job = defaultdict(Decimal)  # (PR item id, job_no) -> Σ allocated qty (from PO side)

    for la in line_allocs:
        ln = la.po_line
        po = ln.po
        j = la.job_no
        if po.status == "cancelled":
            continue

        pr_rates = extract_rates(po.pr.currency_rates_snapshot or {})
        net_eur = to_eur(la.amount, po.currency or "TRY", pr_rates, fb)
        if net_eur is None:
            continue

        row = proj.setdefault(
            j,
            {
                "job_no": j,
                "requested_qty_by_unit": defaultdict(Decimal),
                "ordered_qty_by_unit": defaultdict(Decimal),
                "distinct_items": set(),
                "total_pos": 0,
                "cancelled_pos": 0,
                "active_pos": 0,
                "committed_net_eur": Decimal("0.00"),
                "unpaid_eur": Decimal("0.00"),
                "pending_pr_estimate_eur": Decimal("0.00"),
                "top_suppliers": Counter(),
                "last_activity_at": None,
            },
        )

        row["committed_net_eur"] += net_eur

        # ordered qty by unit (from PR item’s unit if available)
        unit = (
            (getattr(ln.purchase_request_item.item, "unit", "") or "").strip()
            if ln.purchase_request_item_id
            else ""
        )
        row["ordered_qty_by_unit"][unit] += (la.quantity or Decimal("0"))

        # Track ordered qty per (PR item, job) for pending calculation later
        if ln.purchase_request_item_id:
            ordered_qty_by_item_job[(ln.purchase_request_item_id, j)] += (la.quantity or Decimal("0"))

        # supplier mix & activity
        if po.supplier:
            row["top_suppliers"][po.supplier.name] += net_eur
        ts = po.ordered_at or po.created_at
        if ts and (row["last_activity_at"] is None or ts > row["last_activity_at"]):
            row["last_activity_at"] = ts

        # counts per job (count a PO once per job)
        if po.id not in po_seen_by_job[j]:
            po_seen_by_job[j].add(po.id)
            row["total_pos"] += 1
            if po.status == "cancelled":
                row["cancelled_pos"] += 1
            else:
                row["active_pos"] += 1

        po_info.setdefault(
            po.id,
            (
                po.currency or "TRY",
                pr_rates,
                po.status,
                ts,
                po.supplier.name if po.supplier else "",
                po.total_amount or Decimal("0.00"),
            ),
        )
        allo_sum_by_po_job[(po.id, j)] += (la.amount or Decimal("0.00"))

    # --- Apportion UNPAID schedules by allocation share only ---
    for j, po_ids in po_seen_by_job.items():
        row = proj[j]
        for po_id in po_ids:
            cur, pr_rates, status, ts, sup_name, po_total = po_info[po_id]
            if not po_total:
                continue
            allo_sum = allo_sum_by_po_job.get((po_id, j), Decimal("0.00"))
            share = (allo_sum / po_total) if po_total else Decimal("0")
            if share <= 0:
                continue
            schedules = PaymentSchedule.objects.filter(purchase_order_id=po_id, is_paid=False)
            for sch in schedules:
                amt_eur = to_eur(sch.amount, sch.currency or cur, pr_rates, fb)
                if amt_eur is None:
                    continue
                row["unpaid_eur"] += (amt_eur * share)

    # --- Pending PR estimate (recommended ItemOffer totals split by REMAINING PR allocations) ---
    rec_items = (
        ItemOffer.objects.select_related(
            "supplier_offer__purchase_request", "purchase_request_item__item", "supplier_offer"
        ).filter(is_recommended=True)
    )
    if created_gte:
        rec_items = rec_items.filter(supplier_offer__purchase_request__created_at__gte=created_gte)
    if created_lte:
        rec_items = rec_items.filter(supplier_offer__purchase_request__created_at__lte=created_lte)

    # Map PR item -> its allocations, and total PR qty
    pri_all_by_item = defaultdict(list)
    total_pr_qty_by_item = defaultdict(Decimal)
    for a in pri_allocs:
        pri_all_by_item[a.purchase_request_item_id].append(a)
        total_pr_qty_by_item[a.purchase_request_item_id] += (a.quantity or Decimal("0"))

    for io in rec_items:
        pri_id = io.purchase_request_item_id
        pr = io.supplier_offer.purchase_request
        pr_rates = extract_rates(pr.currency_rates_snapshot or {})
        cur = io.supplier_offer.currency or "TRY"
        total_eur = to_eur(io.total_price, cur, pr_rates, fb)
        if total_eur is None:
            continue

        allocs = pri_all_by_item.get(pri_id, [])
        total_pr_qty = total_pr_qty_by_item.get(pri_id, Decimal("0"))
        if total_pr_qty <= 0:
            continue

        # Compute REMAINING qty per allocation (job)
        remaining_slices = []
        remaining_total = Decimal("0")
        for a in allocs:
            ordered = ordered_qty_by_item_job.get((a.purchase_request_item_id, a.job_no), Decimal("0"))
            rem = (a.quantity or Decimal("0")) - ordered
            if rem > 0:
                remaining_slices.append((a, rem))
                remaining_total += rem

        if remaining_total <= 0:
            # Entire PR item is already placed on POs → nothing pending
            continue

        # Allocate offer total by remaining share of the PR item
        for a, rem in remaining_slices:
            share = rem / total_pr_qty
            row = proj.setdefault(
                a.job_no,
                {
                    "job_no": a.job_no,
                    "requested_qty_by_unit": defaultdict(Decimal),
                    "ordered_qty_by_unit": defaultdict(Decimal),
                    "distinct_items": set(),
                    "total_pos": 0,
                    "cancelled_pos": 0,
                    "active_pos": 0,
                    "committed_net_eur": Decimal("0.00"),
                    "unpaid_eur": Decimal("0.00"),
                    "pending_pr_estimate_eur": Decimal("0.00"),
                    "top_suppliers": Counter(),
                    "last_activity_at": None,
                },
            )
            row["pending_pr_estimate_eur"] += (total_eur * share)

    # --- Build rows (drop empties unless include_empty=1) ---
    rows = []
    for j, r in proj.items():
        is_empty = (
            r["active_pos"] == 0
            and r["committed_net_eur"] == 0
            and r["pending_pr_estimate_eur"] == 0
            and len(r["requested_qty_by_unit"]) == 0
            and len(r["ordered_qty_by_unit"]) == 0
        )
        if is_empty and not include_empty:
            continue

        forecast = r["committed_net_eur"] + r["pending_pr_estimate_eur"]

        rows.append(
            {
                "job_no": j,
                "distinct_items": len(r["distinct_items"]),
                "requested_qty_by_unit": {u: str(q2(v)) for u, v in r["requested_qty_by_unit"].items() if u or v},
                "ordered_qty_by_unit": {u: str(q2(v)) for u, v in r["ordered_qty_by_unit"].items() if u or v},
                "total_pos": r["total_pos"],
                "cancelled_pos": r["cancelled_pos"],
                "active_pos": r["active_pos"],
                "committed_net_eur": str(q2(r["committed_net_eur"])),
                "unpaid_eur": str(q2(r["unpaid_eur"])),
                "pending_pr_estimate_eur": str(q2(r["pending_pr_estimate_eur"])),
                "forecast_eur": str(q2(forecast)),
                "top_suppliers_by_spend": [
                    {"name": name, "total_eur": str(q2(val))} for name, val in r["top_suppliers"].most_common(5)
                ],
                "last_activity_at": r["last_activity_at"],
                "currency": "EUR",
            }
        )

    # Ordering (default: -forecast_eur)
    ordering = (request.query_params.get("ordering") or "-forecast_eur").strip()
    if ordering:
        keys = [k.strip() for k in ordering.split(",") if k.strip()]
        for k in reversed(keys):
            rev = k.startswith("-")
            kk = k.lstrip("-")

            def keyer(row):
                if kk in {"forecast_eur", "committed_net_eur", "pending_pr_estimate_eur", "unpaid_eur"}:
                    return float(row[kk])
                if kk == "last_activity_at":
                    return row[kk] or timezone.datetime.min.replace(tzinfo=timezone.utc)
                if kk == "job_no":
                    return row["job_no"] or ""
                return row.get(kk)

            rows.sort(key=keyer, reverse=rev)

    return rows

