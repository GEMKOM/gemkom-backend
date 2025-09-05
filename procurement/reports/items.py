from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
from django.utils import timezone
from django.db.models import Prefetch
from ..models import PurchaseOrderLine, Item
from .common import q2, extract_rates, get_fallback_rates, to_eur

def build_items_report(base_items_qs, request):
    """
    Builds the item report rows (list of dicts), with:
    - buy_count, total_quantity, total_spent_eur
    - avg_unit_price_eur (weighted), min_unit_price_eur
    - suppliers, last_bought_at
    Uses PR snapshot FX first; falls back to today's/latest FX snapshot.
    Filters by the incoming base queryset (so keep your viewset filters there).
    Supports ?ordering=..., multiple keys comma-separated.
    """
    # Fetch only lines for the filtered items, skip cancelled POs
    item_ids = list(base_items_qs.values_list("id", flat=True))
    if not item_ids:
        return []

    lines = (
        PurchaseOrderLine.objects
        .select_related("po", "po__pr", "po__supplier", "purchase_request_item__item")
        .exclude(po__status="cancelled")
        .filter(purchase_request_item__item_id__in=item_ids)
        .only(
            "quantity", "unit_price", "total_price", "delivery_days",
            "po__currency", "po__ordered_at", "po__created_at",
            "po__pr__currency_rates_snapshot",
            "po__supplier__name",
            "purchase_request_item__item_id",
            "purchase_request_item__item__code",
            "purchase_request_item__item__name",
            "purchase_request_item__item__unit",
        )
    )

    fallback_rates = get_fallback_rates()
    by_item = {}
    for ln in lines:
        item = ln.purchase_request_item.item
        pr_rates = extract_rates(ln.po.pr.currency_rates_snapshot or {})
        cur = ln.po.currency or "TRY"

        total_eur = to_eur(ln.total_price, cur, pr_rates, fallback_rates)
        unit_eur  = to_eur(ln.unit_price,  cur, pr_rates, fallback_rates)
        if total_eur is None and unit_eur is None:
            continue

        row = by_item.setdefault(item.id, {
            "item_id": item.id,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "buy_count": 0,
            "total_quantity": Decimal("0"),
            "total_spent_eur": Decimal("0.00"),
            "qty_for_avg": Decimal("0"),
            "sum_unit_eur_x_qty": Decimal("0.00"),
            "min_unit_price_eur": None,
            "suppliers": set(),
            "last_bought_at": None,
        })

        qty = ln.quantity or Decimal("0")
        row["buy_count"] += 1
        row["total_quantity"] += qty

        if total_eur is not None:
            row["total_spent_eur"] += total_eur

        if unit_eur is not None:
            if row["min_unit_price_eur"] is None or unit_eur < row["min_unit_price_eur"]:
                row["min_unit_price_eur"] = unit_eur
            if qty > 0:
                row["qty_for_avg"] += qty
                row["sum_unit_eur_x_qty"] += (unit_eur * qty)

        if ln.po.supplier:
            row["suppliers"].add(ln.po.supplier.name)

        ts = ln.po.ordered_at or ln.po.created_at
        if ts and (row["last_bought_at"] is None or ts > row["last_bought_at"]):
            row["last_bought_at"] = ts

    # Format, drop empty, and sort
    rows = []
    for agg in by_item.values():
        if agg["buy_count"] <= 0:
            continue
        has_total = agg["total_spent_eur"] != Decimal("0.00")
        has_min_or_avg = (agg["min_unit_price_eur"] is not None) or (agg["qty_for_avg"] > 0)
        if not has_total and not has_min_or_avg:
            continue

        avg_unit = None
        if agg["qty_for_avg"] > 0:
            avg_unit = q2(agg["sum_unit_eur_x_qty"] / agg["qty_for_avg"])

        rows.append({
            "item_id": agg["item_id"],
            "code": agg["code"],
            "name": agg["name"],
            "unit": agg["unit"],
            "buy_count": agg["buy_count"],
            "total_quantity": str(q2(agg["total_quantity"])),
            "total_spent_eur": str(q2(agg["total_spent_eur"])),
            "avg_unit_price_eur": (str(avg_unit) if avg_unit is not None else None),
            "min_unit_price_eur": (str(q2(agg["min_unit_price_eur"])) if agg["min_unit_price_eur"] is not None else None),
            "currency": "EUR",
            "suppliers": sorted(agg["suppliers"]),
            "last_bought_at": agg["last_bought_at"],
        })

    # ordering
    ordering = (request.query_params.get("ordering") or "").strip()
    if ordering:
        keys = [k.strip() for k in ordering.split(",") if k.strip()]
        for k in reversed(keys):
            rev = k.startswith("-"); kk = k.lstrip("-")
            def keyer(r):
                if kk in {"total_spent_eur", "avg_unit_price_eur", "min_unit_price_eur"}:
                    return Decimal(r[kk] or "0")
                if kk == "total_quantity":
                    return Decimal(r["total_quantity"])
                if kk in {"buy_count"}:
                    return r[kk]
                if kk in {"code", "name"}:
                    return r[kk] or ""
                if kk == "last_bought_at":
                    return r[kk] or timezone.datetime.min.replace(tzinfo=timezone.utc)
                return r.get(kk)
            rows.sort(key=keyer, reverse=rev)

    return rows
