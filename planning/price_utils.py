"""
Price resolution cascade for PlanningRequestItem.

Mirrors the logic in projects/views.py JobOrderProcurementLineViewSet.preview,
but returns a simple dict (or None) instead of building a full result row.

Tiers:
  1. PurchaseOrderLine via FK  (purchase_request_item.planning_request_item = pri)
  2. PurchaseOrderLine via M2M (PurchaseRequest.planning_request_items ∋ pri, same item)
  3. Recommended ItemOffer     (FK path)
  4. Any ItemOffer             (FK path)
  5. Latest historical PO line for the same Item (any job)

Returns:
    {
        'unit_price_eur': Decimal,
        'original_unit_price': Decimal,
        'original_currency': str,
        'price_source': str,   # 'po_line' | 'recommended_offer' | 'any_offer' | 'historical_po'
        'price_date': date,
    }
    or None if no price found at any tier.
"""
from decimal import Decimal


def _ex_tax(gross, tax_rate):
    rate = tax_rate or Decimal('0')
    if rate == 0:
        return gross
    return gross / (1 + rate / Decimal('100'))


def resolve_planning_item_price(pri):
    """
    Run the 5-tier price cascade for a PlanningRequestItem instance.

    Tiers 1, 3, 4 use prefetched purchase_request_items__po_lines__po and
    purchase_request_items__offers__supplier_offer (no extra DB queries).
    Tiers 3/4 filter in Python to avoid re-querying the prefetch cache.

    Tiers 2 and 5 read from queryset annotations (_t2_* and _t5_*) set by
    PlanningRequestItemViewSet.get_queryset() — also no per-item DB queries.
    """
    from projects.services.costing import convert_to_eur

    # --- Tier 1: PurchaseOrderLine via FK (prefetched) ---
    po_line = None
    for pri_item in pri.purchase_request_items.all():
        if pri_item.purchase_request.status == 'cancelled':
            continue
        for line in pri_item.po_lines.all():
            if line.po.status != 'cancelled':
                po_line = line
                break
        if po_line:
            break
    if po_line:
        net = _ex_tax(po_line.unit_price, po_line.po.tax_rate)
        ref_date = (
            po_line.po.ordered_at.date() if po_line.po.ordered_at
            else po_line.po.created_at.date()
        )
        return {
            'unit_price_eur': convert_to_eur(net, po_line.po.currency, ref_date),
            'original_unit_price': net,
            'original_currency': po_line.po.currency,
            'price_source': 'po_line',
            'price_date': ref_date,
        }

    # --- Tier 2: PurchaseOrderLine via M2M (annotation) ---
    t2_price = getattr(pri, '_t2_price', None)
    if t2_price is not None:
        t2_currency = getattr(pri, '_t2_currency', 'TRY') or 'TRY'
        t2_tax      = getattr(pri, '_t2_tax', None)
        t2_date_raw = getattr(pri, '_t2_date', None)
        net = _ex_tax(Decimal(str(t2_price)), t2_tax)
        ref_date = t2_date_raw.date() if t2_date_raw and hasattr(t2_date_raw, 'date') else t2_date_raw
        return {
            'unit_price_eur': convert_to_eur(net, t2_currency, ref_date),
            'original_unit_price': net,
            'original_currency': t2_currency,
            'price_source': 'po_line',
            'price_date': ref_date,
        }

    # --- Tier 3: Recommended ItemOffer (prefetched, filtered in Python) ---
    offer = None
    for pri_item in pri.purchase_request_items.all():
        if pri_item.purchase_request.status == 'cancelled':
            continue
        for o in pri_item.offers.all():
            if o.is_recommended:
                offer = o
                break
        if offer:
            break
    if offer:
        net = _ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
        ref_date = offer.supplier_offer.created_at.date()
        return {
            'unit_price_eur': convert_to_eur(net, offer.supplier_offer.currency, ref_date),
            'original_unit_price': net,
            'original_currency': offer.supplier_offer.currency,
            'price_source': 'recommended_offer',
            'price_date': ref_date,
        }

    # --- Tier 4: Any ItemOffer (prefetched, filtered in Python) ---
    offer = None
    for pri_item in pri.purchase_request_items.all():
        if pri_item.purchase_request.status == 'cancelled':
            continue
        for o in pri_item.offers.all():
            offer = o
            break
        if offer:
            break
    if offer:
        net = _ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
        ref_date = offer.supplier_offer.created_at.date()
        return {
            'unit_price_eur': convert_to_eur(net, offer.supplier_offer.currency, ref_date),
            'original_unit_price': net,
            'original_currency': offer.supplier_offer.currency,
            'price_source': 'any_offer',
            'price_date': ref_date,
        }

    # --- Tier 5: Latest historical PO line for same item (annotation) ---
    t5_price = getattr(pri, '_t5_price', None)
    if t5_price is not None:
        t5_currency = getattr(pri, '_t5_currency', 'TRY') or 'TRY'
        t5_tax      = getattr(pri, '_t5_tax', None)
        t5_date_raw = getattr(pri, '_t5_date', None)
        net = _ex_tax(Decimal(str(t5_price)), t5_tax)
        ref_date = t5_date_raw.date() if hasattr(t5_date_raw, 'date') else t5_date_raw
        return {
            'unit_price_eur': convert_to_eur(net, t5_currency, ref_date),
            'original_unit_price': net,
            'original_currency': t5_currency,
            'price_source': 'historical_po',
            'price_date': ref_date,
        }

    return None


def resolve_item_price(item):
    """
    Run the price cascade for a catalog Item (no PlanningRequestItem context).

    Tiers:
      1. Latest PO line for this item (any job)           → 'po_line'
      2. Latest recommended ItemOffer for this item       → 'recommended_offer'
      3. Latest any ItemOffer for this item               → 'any_offer'

    Expects `requests` (PurchaseRequestItem reverse FK) to be prefetched with
    `po_lines__po` and `offers__supplier_offer` on the item.
    """
    from projects.services.costing import convert_to_eur

    # --- Tier 1: Latest PO line for this item ---
    po_line = None
    for pri in item.requests.all():
        for line in pri.po_lines.all():
            if line.po.status != 'cancelled':
                po_line = line
                break
        if po_line:
            break
    if po_line:
        net = _ex_tax(po_line.unit_price, po_line.po.tax_rate)
        ref_date = (
            po_line.po.ordered_at.date() if po_line.po.ordered_at
            else po_line.po.created_at.date()
        )
        return {
            'unit_price_eur': convert_to_eur(net, po_line.po.currency, ref_date),
            'original_unit_price': net,
            'original_currency': po_line.po.currency,
            'price_source': 'po_line',
            'price_date': ref_date,
        }

    # --- Tier 2: Latest recommended ItemOffer for this item ---
    offer = None
    for pri in item.requests.all():
        for o in pri.offers.all():
            if o.is_recommended:
                offer = o
                break
        if offer:
            break
    if offer:
        net = _ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
        ref_date = offer.supplier_offer.created_at.date()
        return {
            'unit_price_eur': convert_to_eur(net, offer.supplier_offer.currency, ref_date),
            'original_unit_price': net,
            'original_currency': offer.supplier_offer.currency,
            'price_source': 'recommended_offer',
            'price_date': ref_date,
        }

    # --- Tier 3: Any ItemOffer for this item ---
    offer = None
    for pri in item.requests.all():
        for o in pri.offers.all():
            offer = o
            break
        if offer:
            break
    if offer:
        net = _ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
        ref_date = offer.supplier_offer.created_at.date()
        return {
            'unit_price_eur': convert_to_eur(net, offer.supplier_offer.currency, ref_date),
            'original_unit_price': net,
            'original_currency': offer.supplier_offer.currency,
            'price_source': 'any_offer',
            'price_date': ref_date,
        }

    return None
