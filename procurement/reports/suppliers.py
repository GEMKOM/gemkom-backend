from __future__ import annotations
from collections import defaultdict, Counter
from decimal import Decimal
from django.db.models import Prefetch, Q
from django.utils import timezone
from ..models import Supplier, PurchaseOrder, PaymentSchedule
from .common import q2, bool_param, split_param, extract_rates, get_fallback_rates, to_eur

def build_suppliers_report(suppliers_qs, request):
    """
    Supplier report with:
      - total_pos, cancelled_pos, total_post (active)
      - total_spent_eur, total_tax_eur, total_gross_eur, unpaid_amount_eur
      - last_purchase_at, distinct_items, top_items_by_spend, avg_delivery_days_weighted
      - currencies_used, payment_terms_used
    Filters: name, code, has_dbs, created_[gte|lte], status, min_total_spent_eur
    Ordering: -total_spent_eur (default), or any of:
      total_gross_eur,total_post,cancelled_pos,avg_delivery_days_weighted,last_purchase_at,unpaid_amount_eur,name,code
    """
    try:
        sup_qs = suppliers_qs or Supplier.objects.none()
        name_q = request.query_params.get("name")
        code_q = request.query_params.get("code")
        has_dbs_q = bool_param(request.query_params.get("has_dbs"))
        created_gte = request.query_params.get("created_gte")
        created_lte = request.query_params.get("created_lte")
        status_param = request.query_params.get("status")
        status_list = set(split_param(status_param)) if status_param else set()
        min_total_spent_eur = request.query_params.get("min_total_spent_eur")

        sup_qs = suppliers_qs
        if name_q: sup_qs = sup_qs.filter(name__icontains=name_q)
        if code_q: sup_qs = sup_qs.filter(code__icontains=code_q)
        if has_dbs_q is not None: sup_qs = sup_qs.filter(has_dbs=has_dbs_q)

        po_filter = Q()
        if created_gte:
            po_filter &= (Q(created_at__gte=created_gte) | Q(ordered_at__gte=created_gte))
        if created_lte:
            po_filter &= (Q(created_at__lte=created_lte) | Q(ordered_at__lte=created_lte))
        if status_list:
            po_filter &= Q(status__in=list(status_list))

        po_qs = (
            PurchaseOrder.objects
            .select_related("pr", "supplier_offer__payment_terms", "supplier")
            .prefetch_related("lines__purchase_request_item__item", "payment_schedules")
        )
        if po_filter:
            po_qs = po_qs.filter(po_filter)

        sup_qs = sup_qs.prefetch_related(Prefetch("purchase_orders", queryset=po_qs))

        fallback_rates = get_fallback_rates()
        rows = []

        for sup in sup_qs:
            pos = list(sup.purchase_orders.all())
            total_pos = len(pos)
            cancelled_pos = sum(1 for po in pos if po.status == "cancelled")
            total_post = total_pos - cancelled_pos

            total_spent_eur = Decimal("0.00")
            total_tax_eur   = Decimal("0.00")
            unpaid_amount_eur = Decimal("0.00")
            last_purchase_at = None

            item_spend = defaultdict(Decimal)
            item_identity = {}
            distinct_items = set()
            currencies_used = set()
            pt_counter = Counter()
            w_sum = Decimal("0.00")
            w_days = Decimal("0.00")

            for po in pos:
                currencies_used.add((po.currency or "TRY").upper())
                ts = po.ordered_at or po.created_at
                if ts and (last_purchase_at is None or ts > last_purchase_at):
                    last_purchase_at = ts

                if po.status != "cancelled" and po.supplier_offer and po.supplier_offer.payment_terms:
                    pt_counter[po.supplier_offer.payment_terms.code] += 1

                if po.status == "cancelled":
                    continue

                pr_rates = extract_rates(po.pr.currency_rates_snapshot or {})
                net_eur = to_eur(po.total_amount, po.currency, pr_rates, fallback_rates)
                tax_eur = to_eur(po.total_tax_amount, po.currency, pr_rates, fallback_rates)
                if net_eur is not None:
                    total_spent_eur += net_eur
                if tax_eur is not None:
                    total_tax_eur += tax_eur

                for sch in po.payment_schedules.all():
                    if not sch.is_paid:
                        amt_eur = to_eur(sch.amount, getattr(sch, "currency", po.currency), pr_rates, fallback_rates)
                        if amt_eur is not None:
                            unpaid_amount_eur += amt_eur

                for ln in po.lines.all():
                    it = ln.purchase_request_item.item
                    distinct_items.add(it.id)
                    item_identity[it.id] = (it.code, it.name)
                    line_eur = to_eur(ln.total_price, po.currency, pr_rates, fallback_rates)
                    if line_eur is not None:
                        item_spend[it.id] += line_eur
                        if ln.delivery_days is not None:
                            w_sum += line_eur
                            w_days += (Decimal(str(ln.delivery_days)) * line_eur)

            total_gross_eur = total_spent_eur + total_tax_eur
            top_items = sorted(
                ({"code": item_identity[i][0], "name": item_identity[i][1], "total_spent_eur": str(q2(val))}
                for i, val in item_spend.items()),
                key=lambda x: Decimal(x["total_spent_eur"]),
                reverse=True
            )[:5]

            avg_delivery_days_weighted = None
            if w_sum > 0:
                avg_delivery_days_weighted = int((q2(w_days / w_sum)).quantize(Decimal("1")))

            row = {
                "supplier_id": sup.id,
                "code": sup.code,
                "name": sup.name,
                "default_currency": sup.default_currency,
                "has_dbs": sup.has_dbs,
                "dbs_bank": sup.dbs_bank,
                "dbs_limit": (str(q2(sup.dbs_limit)) if sup.dbs_limit is not None else None),
                "dbs_currency": sup.dbs_currency,

                "total_pos": total_pos,
                "cancelled_pos": cancelled_pos,
                "total_post": total_post,

                "total_spent_eur": str(q2(total_spent_eur)),
                "total_tax_eur": str(q2(total_tax_eur)),
                "total_gross_eur": str(q2(total_gross_eur)),
                "unpaid_amount_eur": str(q2(unpaid_amount_eur)),

                "last_purchase_at": last_purchase_at,
                "distinct_items": len(distinct_items),
                "top_items_by_spend": top_items,
                "avg_delivery_days_weighted": avg_delivery_days_weighted,
                "currencies_used": sorted(currencies_used),
                "payment_terms_used": [{"code": code, "count": cnt} for code, cnt in pt_counter.most_common()],
            }
            rows.append(row)

        # post-aggregation filter
        if min_total_spent_eur:
            thr = Decimal(str(min_total_spent_eur))
            rows = [r for r in rows if Decimal(r["total_spent_eur"]) >= thr]

        # ordering (default -total_spent_eur)
        ordering = (request.query_params.get("ordering") or "-total_spent_eur").strip()
        if ordering:
            keys = [k.strip() for k in ordering.split(",") if k.strip()]
            for k in reversed(keys):
                rev = k.startswith("-"); kk = k.lstrip("-")
                def keyer(r):
                    if kk in {"total_spent_eur", "total_gross_eur", "unpaid_amount_eur"}:
                        return Decimal(r[kk])
                    if kk in {"total_post", "cancelled_pos", "distinct_items"}:
                        return r[kk]
                    if kk == "avg_delivery_days_weighted":
                        return r[kk] if r[kk] is not None else -1
                    if kk == "last_purchase_at":
                        return r[kk] or timezone.datetime.min.replace(tzinfo=timezone.utc)
                    if kk in {"name", "code"}:
                        return r[kk] or ""
                    return r.get(kk)
                rows.sort(key=keyer, reverse=rev)

        return rows
    except Exception as e:
        return []
