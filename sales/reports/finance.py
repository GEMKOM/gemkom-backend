from __future__ import annotations
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta, date as date_type
from django.db.models import Q

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
    created_gte = request.query_params.get("created_gte")
    created_lte = request.query_params.get("created_lte")

    qs = (
        SalesOffer.objects
        .filter(status="converted")
        .select_related("converted_job_order", "payment_terms", "customer")
        .prefetch_related("price_revisions")
    )
    if created_gte:
        qs = qs.filter(Q(won_at__date__gte=created_gte) | Q(created_at__date__gte=created_gte))
    if created_lte:
        qs = qs.filter(Q(won_at__date__lte=created_lte) | Q(created_at__date__lte=created_lte))

    fb = get_fallback_rates()

    by_month = defaultdict(lambda: {
        "revenue_eur": Decimal("0.00"),
        "offer_ids": set(),
        "customer_ids": set(),
    })
    undated = {
        "revenue_eur": Decimal("0.00"),
        "offer_ids": set(),
    }

    for offer in qs:
        current_price = next(
            (r for r in offer.price_revisions.all() if r.is_current),
            None,
        )
        if not current_price or not current_price.amount:
            continue

        total_eur = to_eur(
            current_price.amount,
            current_price.currency or "EUR",
            {},
            fb,
        )
        if not total_eur:
            continue

        job = offer.converted_job_order

        # Build installment lines — use payment terms if set, else treat as single 100% completion payment
        if offer.payment_terms and offer.payment_terms.default_lines:
            lines = offer.payment_terms.default_lines
        else:
            lines = [{"percentage": Decimal("100.00"), "basis": "on_delivery", "offset_days": 0}]

        for line in lines:
            pct = Decimal(str(line.get("percentage") or 0))
            if pct <= 0:
                continue
            basis = line.get("basis") or "custom"
            offset_days = line.get("offset_days") or 0
            installment_eur = q2(total_eur * pct / Decimal("100"))

            date = _resolve_installment_date(basis, offset_days, offer, job)

            if date is None:
                undated["revenue_eur"] += installment_eur
                undated["offer_ids"].add(offer.id)
            else:
                mk = f"{date.year:04d}-{date.month:02d}"
                by_month[mk]["revenue_eur"] += installment_eur
                by_month[mk]["offer_ids"].add(offer.id)
                by_month[mk]["customer_ids"].add(offer.customer_id)

    # Build sorted series
    months = sorted(by_month.keys())
    series = []
    total_revenue_all = Decimal("0.00")
    all_offer_ids = set()
    all_customer_ids = set()

    for m in months:
        row = by_month[m]
        total_revenue_all += row["revenue_eur"]
        all_offer_ids |= row["offer_ids"]
        all_customer_ids |= row["customer_ids"]
        series.append({
            "month": m,
            "revenue_eur": str(q2(row["revenue_eur"])),
            "offer_count": len(row["offer_ids"]),
            "customer_count": len(row["customer_ids"]),
        })

    # MoM / YoY on latest month
    latest = months[-1] if months else None
    mom = yoy = None
    if latest:
        yyyy, mm = map(int, latest.split("-"))
        prev_m = f"{(yyyy if mm > 1 else yyyy - 1):04d}-{(mm - 1 if mm > 1 else 12):02d}"
        last_year = f"{yyyy - 1:04d}-{mm:02d}"
        cur_val = by_month[latest]["revenue_eur"]
        if prev_m in by_month and by_month[prev_m]["revenue_eur"] > 0:
            mom = float((cur_val - by_month[prev_m]["revenue_eur"]) / by_month[prev_m]["revenue_eur"]) * 100.0
        if last_year in by_month and by_month[last_year]["revenue_eur"] > 0:
            yoy = float((cur_val - by_month[last_year]["revenue_eur"]) / by_month[last_year]["revenue_eur"]) * 100.0

    return {
        "kpis": {
            "total_revenue_eur": str(q2(total_revenue_all)),
            "offer_count": len(all_offer_ids),
            "customer_count": len(all_customer_ids),
            "mom_percent": round(mom, 2) if mom is not None else None,
            "yoy_percent": round(yoy, 2) if yoy is not None else None,
        },
        "series": series,
        "undated": {
            "revenue_eur": str(q2(undated["revenue_eur"])),
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
