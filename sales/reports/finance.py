from __future__ import annotations
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta, date as date_type

from ..models import SalesOffer
from procurement.reports.common import q2, get_fallback_rates, to_eur


def _resolve_installment_date(basis, offset_days, offer, job):
    """
    Map a payment term installment basis to a concrete date.
    Returns a date or None (caller puts None into undated bucket).
    """
    offset = timedelta(days=int(offset_days or 0))

    if basis == "immediate":
        anchor = None
        if offer.won_at:
            anchor = offer.won_at.date()
        elif job and job.created_at:
            anchor = job.created_at.date()
        return (anchor + offset) if anchor else None

    # All other bases anchor to job completion / created_at
    if job is None:
        return None

    completion = job.target_completion_date  # DateField, already a date
    fallback = job.created_at.date() if job.created_at else None
    anchor = completion or fallback
    return (anchor + offset) if anchor else None


def build_sales_revenue_forecast(request):
    from finance.models import ExpectedReceiptInstallment

    qs = (
        SalesOffer.objects
        .filter(status="converted")
        .select_related("converted_job_order", "payment_terms", "customer")
        .prefetch_related("price_revisions")
    )

    fb = get_fallback_rates()

    by_month = defaultdict(lambda: {
        "sales_offers_eur": Decimal("0.00"),
        "expected_receipts_eur": Decimal("0.00"),
        "offer_ids": set(),
        "customer_ids": set(),
    })
    undated = {
        "sales_offers_eur": Decimal("0.00"),
        "expected_receipts_eur": Decimal("0.00"),
        "offer_ids": set(),
    }

    # Pre-fetch all receipt states for converted offers
    from finance.models import SalesOfferInstallmentReceipt
    offer_ids = list(qs.values_list("id", flat=True))
    receipt_map = {}  # (offer_id, sequence) -> SalesOfferInstallmentReceipt
    for r in SalesOfferInstallmentReceipt.objects.filter(offer_id__in=offer_ids):
        receipt_map[(r.offer_id, r.sequence)] = r

    # --- Sales offer installments ---
    for offer in qs:
        current_price = next(
            (r for r in offer.price_revisions.all() if r.is_current),
            None,
        )
        if not current_price or not current_price.amount:
            continue

        total_eur = to_eur(current_price.amount, current_price.currency or "EUR", {}, fb)
        if not total_eur:
            continue

        job = offer.converted_job_order

        if offer.payment_terms and offer.payment_terms.default_lines:
            lines = offer.payment_terms.default_lines
        else:
            lines = [{"percentage": Decimal("100.00"), "basis": "on_delivery", "offset_days": 0}]

        for seq, line in enumerate(lines, start=1):
            pct = Decimal(str(line.get("percentage") or 0))
            if pct <= 0:
                continue
            basis = line.get("basis") or "custom"
            offset_days = line.get("offset_days") or 0
            installment_eur = q2(total_eur * pct / Decimal("100"))

            resolved = _resolve_installment_date(basis, offset_days, offer, job)
            rec = receipt_map.get((offer.id, seq))
            is_received = rec.is_received if rec else False

            if resolved is None:
                undated["sales_offers_eur"] += installment_eur
                undated["offer_ids"].add(offer.id)
            else:
                mk = f"{resolved.year:04d}-{resolved.month:02d}"
                by_month[mk]["sales_offers_eur"] += installment_eur
                by_month[mk]["offer_ids"].add(offer.id)
                by_month[mk]["customer_ids"].add(offer.customer_id)
                if is_received:
                    by_month[mk].setdefault("sales_offers_received_eur", Decimal("0"))
                    by_month[mk]["sales_offers_received_eur"] += installment_eur

    # --- Expected receipt installments ---
    receipt_installments = (
        ExpectedReceiptInstallment.objects
        .select_related("receipt")
        .exclude(receipt__status="cancelled")
    )
    for inst in receipt_installments:
        amt_eur = to_eur(inst.amount, inst.currency, {}, fb) or Decimal("0")
        if not inst.due_date:
            undated["expected_receipts_eur"] += amt_eur
        else:
            mk = f"{inst.due_date.year:04d}-{inst.due_date.month:02d}"
            by_month[mk]["expected_receipts_eur"] += amt_eur

    # --- Build sorted series ---
    months = sorted(by_month.keys())
    series = []
    total_sales_all = Decimal("0.00")
    total_receipts_all = Decimal("0.00")
    all_offer_ids = set()
    all_customer_ids = set()

    for m in months:
        row = by_month[m]
        total_sales_all += row["sales_offers_eur"]
        total_receipts_all += row["expected_receipts_eur"]
        all_offer_ids |= row["offer_ids"]
        all_customer_ids |= row["customer_ids"]
        total_inflow = row["sales_offers_eur"] + row["expected_receipts_eur"]
        sales_received = row.get("sales_offers_received_eur", Decimal("0"))
        series.append({
            "month": m,
            "sales_offers_eur": str(q2(row["sales_offers_eur"])),
            "sales_offers_received_eur": str(q2(sales_received)),
            "sales_offers_awaiting_eur": str(q2(row["sales_offers_eur"] - sales_received)),
            "expected_receipts_eur": str(q2(row["expected_receipts_eur"])),
            "total_inflow_eur": str(q2(total_inflow)),
            "offer_count": len(row["offer_ids"]),
            "customer_count": len(row["customer_ids"]),
        })

    # MoM / YoY on total_inflow of latest month
    latest = months[-1] if months else None
    mom = yoy = None
    if latest:
        yyyy, mm = map(int, latest.split("-"))
        prev_m = f"{(yyyy if mm > 1 else yyyy - 1):04d}-{(mm - 1 if mm > 1 else 12):02d}"
        last_year = f"{yyyy - 1:04d}-{mm:02d}"

        def _total_inflow(mk):
            r = by_month.get(mk)
            if not r:
                return Decimal("0")
            return r["sales_offers_eur"] + r["expected_receipts_eur"]

        cur_val = _total_inflow(latest)
        prev_val = _total_inflow(prev_m)
        yr_val = _total_inflow(last_year)
        if prev_val > 0:
            mom = float((cur_val - prev_val) / prev_val) * 100.0
        if yr_val > 0:
            yoy = float((cur_val - yr_val) / yr_val) * 100.0

    grand_total = total_sales_all + total_receipts_all

    return {
        "kpis": {
            "total_inflow_eur": str(q2(grand_total)),
            "total_sales_offers_eur": str(q2(total_sales_all)),
            "total_expected_receipts_eur": str(q2(total_receipts_all)),
            "offer_count": len(all_offer_ids),
            "customer_count": len(all_customer_ids),
            "mom_percent": round(mom, 2) if mom is not None else None,
            "yoy_percent": round(yoy, 2) if yoy is not None else None,
        },
        "series": series,
        "undated": {
            "sales_offers_eur": str(q2(undated["sales_offers_eur"])),
            "expected_receipts_eur": str(q2(undated["expected_receipts_eur"])),
            "offer_count": len(undated["offer_ids"]),
        },
    }


def build_inflow_detail(month: str):
    """
    Returns per-offer inflow detail for a given month (YYYY-MM).
    Each row is one installment from a converted offer whose resolved date falls in that month.
    """
    try:
        year, mon = map(int, month.split("-"))
    except (ValueError, AttributeError):
        return []

    fb = get_fallback_rates()

    offers = (
        SalesOffer.objects
        .filter(status="converted")
        .select_related("converted_job_order", "payment_terms", "customer")
        .prefetch_related("price_revisions")
    )

    rows = []
    for offer in offers:
        current_price = next(
            (r for r in offer.price_revisions.all() if r.is_current), None
        )
        if not current_price or not current_price.amount:
            continue

        total_eur = to_eur(current_price.amount, current_price.currency or "EUR", {}, fb)
        if not total_eur:
            continue

        job = offer.converted_job_order

        lines = (
            offer.payment_terms.default_lines
            if offer.payment_terms and offer.payment_terms.default_lines
            else [{"percentage": Decimal("100.00"), "basis": "on_delivery", "offset_days": 0}]
        )

        for line in lines:
            pct = Decimal(str(line.get("percentage") or 0))
            if pct <= 0:
                continue
            basis = line.get("basis") or "custom"
            offset_days = line.get("offset_days") or 0

            resolved = _resolve_installment_date(basis, offset_days, offer, job)
            if resolved is None or resolved.year != year or resolved.month != mon:
                continue

            installment_eur = q2(total_eur * pct / Decimal("100"))

            rows.append({
                "offer_id": offer.id,
                "offer_no": offer.offer_no,
                "offer_title": offer.title,
                "customer_id": offer.customer_id,
                "customer_name": offer.customer.name if offer.customer else None,
                "customer_code": offer.customer.code if offer.customer else None,
                "won_at": offer.won_at.date().isoformat() if offer.won_at else None,
                "order_no": offer.order_no or None,
                "payment_terms_name": offer.payment_terms.name if offer.payment_terms else None,
                "installment_label": line.get("label") or basis,
                "installment_basis": basis,
                "installment_percentage": str(pct),
                "installment_due_date": resolved.isoformat(),
                "original_amount": str(q2(current_price.amount)),
                "original_currency": current_price.currency or "EUR",
                "installment_amount_original": str(q2(current_price.amount * pct / Decimal("100"))),
                "installment_amount_eur": str(installment_eur),
                "job_no": job.job_no if job else None,
                "job_title": job.title if job else None,
                "job_status": job.status if job else None,
                "job_target_completion_date": job.target_completion_date.isoformat() if job and job.target_completion_date else None,
                "job_completion_percentage": str(job.completion_percentage) if job else None,
            })

    rows.sort(key=lambda r: r["customer_name"] or "")
    return rows
