# procurement/reports/procurement_staff.py
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
from django.db.models import Q, Prefetch
from django.utils import timezone

from ..models import PurchaseRequest, PurchaseRequestItem, PurchaseOrder, PurchaseOrderLine
from .common import q2, extract_rates, get_fallback_rates, to_eur

def build_procurement_staff_report(users_qs, request):
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")
    username_q  = request.query_params.get("username")

    pr_time_q = Q()
    if created_gte: pr_time_q &= Q(created_at__gte=created_gte)
    if created_lte: pr_time_q &= Q(created_at__lte=created_lte)

    # ✅ Only prefetch what actually exists on User: 'purchase_requests'
    prs_prefetch = Prefetch(
        "purchase_requests",
        queryset=PurchaseRequest.objects.filter(pr_time_q) if pr_time_q else PurchaseRequest.objects.all(),
        to_attr="_prefetched_prs",
    )

    users = users_qs.select_related("profile").prefetch_related(prs_prefetch)
    if username_q:
        users = users.filter(username__icontains=username_q)

    fallback_rates = get_fallback_rates()

    rows = []
    for u in users:
        # PRs created by this user (from prefetch if present)
        prs = list(getattr(u, "_prefetched_prs", []))
        if not prs and pr_time_q:
            prs = list(PurchaseRequest.objects.filter(requestor=u).filter(pr_time_q))
        elif not prs:
            prs = list(PurchaseRequest.objects.filter(requestor=u))

        pr_ids   = [pr.id for pr in prs]
        pr_count = len(prs)

        # ✅ Fetch POs through PR → User (no invalid prefetch on User)
        po_qs = (
            PurchaseOrder.objects
            .filter(pr__requestor=u)
            .exclude(status="cancelled")
            .select_related("pr", "supplier")
            .prefetch_related("lines__purchase_request_item__item")
        )
        if created_gte:
            po_qs = po_qs.filter(Q(created_at__gte=created_gte) | Q(ordered_at__gte=created_gte))
        if created_lte:
            po_qs = po_qs.filter(Q(created_at__lte=created_lte) | Q(ordered_at__lte=created_lte))
        pos = list(po_qs)
        po_count = len(pos)

        # Totals
        total_spent_eur = Decimal("0.00")
        total_tax_eur   = Decimal("0.00")
        last_activity_at = None

        # Requested items/qty by unit
        requested_qty_by_unit = defaultdict(Decimal)
        distinct_item_ids = set()

        # Order lines qty by unit
        ordered_qty_by_unit = defaultdict(Decimal)

        # PR items (requested quantities)
        if pr_ids:
            pri_qs = (
                PurchaseRequestItem.objects
                .select_related("item", "purchase_request")
                .filter(purchase_request_id__in=pr_ids)
            )
            if pr_time_q:
                pri_qs = pri_qs.filter(purchase_request__in=prs)
            for pri in pri_qs:
                unit = (pri.item.unit or "").strip() if pri.item else ""
                qty = pri.quantity or Decimal("0")
                requested_qty_by_unit[unit] += qty
                if pri.item_id:
                    distinct_item_ids.add(pri.item_id)

        # POs totals and line quantities
        for po in pos:
            # latest activity
            ts = po.ordered_at or po.created_at
            if ts and (last_activity_at is None or ts > last_activity_at):
                last_activity_at = ts

            pr_rates = extract_rates(po.pr.currency_rates_snapshot or {}) if po.pr_id else {}
            net_eur = to_eur(po.total_amount, po.currency or "TRY", pr_rates, fallback_rates)
            tax_eur = to_eur(po.total_tax_amount, po.currency or "TRY", pr_rates, fallback_rates)
            if net_eur is not None: total_spent_eur += net_eur
            if tax_eur is not None: total_tax_eur += tax_eur

            for ln in po.lines.all():
                unit = (getattr(ln.purchase_request_item.item, "unit", "") or "").strip() if ln.purchase_request_item_id else ""
                qty  = ln.quantity or Decimal("0")
                ordered_qty_by_unit[unit] += qty

        total_gross_eur = total_spent_eur + total_tax_eur

        # Skip empty users (mirror items/suppliers behavior)
        if pr_count == 0 and po_count == 0 and total_spent_eur == 0 and len(distinct_item_ids) == 0:
            continue

        rows.append({
            "user_id": u.id,
            "username": u.username,
            "full_name": getattr(u, "get_full_name", lambda: "")() or f"{getattr(u, 'first_name', '')} {getattr(u, 'last_name','')}".strip(),
            "team": getattr(getattr(u, "profile", None), "team", None),

            "pr_count": pr_count,
            "po_count": po_count,

            "total_spent_eur": str(q2(total_spent_eur)),
            "total_tax_eur": str(q2(total_tax_eur)),
            "total_gross_eur": str(q2(total_gross_eur)),

            "distinct_items_in_prs": len(distinct_item_ids),
            "requested_qty_by_unit": {k: str(q2(v)) for k, v in requested_qty_by_unit.items() if k or v},
            "ordered_qty_by_unit":   {k: str(q2(v)) for k, v in ordered_qty_by_unit.items() if k or v},

            "last_activity_at": last_activity_at,
            "currency": "EUR",
        })

    # Ordering
    ordering = (request.query_params.get("ordering") or "-total_spent_eur").strip()
    if ordering:
        keys = [k.strip() for k in ordering.split(",") if k.strip()]
        for k in reversed(keys):
            rev = k.startswith("-"); kk = k.lstrip("-")
            def keyer(r):
                if kk in {"total_spent_eur", "total_gross_eur"}:
                    return Decimal(r[kk])
                if kk in {"pr_count", "po_count", "distinct_items_in_prs"}:
                    return r[kk]
                if kk == "last_activity_at":
                    return r[kk] or timezone.datetime.min.replace(tzinfo=timezone.utc)
                if kk == "username":
                    return r[kk] or ""
                return r.get(kk)
            rows.sort(key=keyer, reverse=rev)

    return rows
