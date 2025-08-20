# services/po_from_recommended.py
from collections import defaultdict
from decimal import Decimal
from django.db import transaction

from app.models import PurchaseOrder, PurchaseOrderLine, ItemOffer  # adjust import path

@transaction.atomic
def create_pos_from_recommended(pr):
    """
    Build Purchase Orders from ItemOffer.is_recommended=True for a given PR.
    Idempotent guard: if PR already has POs, do nothing.
    Returns list of created POs.
    """
    if pr.purchase_orders.exists():
        return []

    rec_offers = (
        ItemOffer.objects
        .select_related(
            'purchase_request_item',
            'supplier_offer', 'supplier_offer__supplier'
        )
        .filter(purchase_request_item__purchase_request=pr, is_recommended=True)
    )
    if not rec_offers.exists():
        return []

    grouped = defaultdict(list)
    for io in rec_offers:
        grouped[io.supplier_offer].append(io)

    pos = []
    for so, item_offers in grouped.items():
        supplier = so.supplier
        po = PurchaseOrder.objects.create(
            pr=pr,
            supplier_offer=so,
            supplier=supplier,
            currency=(supplier.default_currency or supplier.currency or 'TRY'),
            priority=pr.priority,
            status='awaiting_invoice',
        )

        for io in item_offers:
            pri = io.purchase_request_item
            qty = pri.quantity
            unit = io.unit_price
            total = (qty * unit).quantize(Decimal('0.01'))
            PurchaseOrderLine.objects.create(
                po=po,
                item_offer=io,
                purchase_request_item=pri,
                quantity=qty,
                unit_price=unit,
                total_price=total,
                delivery_days=io.delivery_days,
                notes=io.notes or '',
            )

        po.recompute_totals()
        pos.append(po)

    return pos
