# services/po_from_recommended.py
from collections import defaultdict
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError

from .models import PurchaseOrder, PurchaseOrderLine, ItemOffer  # adjust import path

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
            currency=(supplier.currency or supplier.default_currency or 'TRY'),
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

def _all_pos_cancellable(pr):
    # define your own rule; for now: POs exist AND all are in a cancellable state
    pos = list(pr.purchase_orders.all())
    if not pos:
        return True
    return all(po.status in ('awaiting_invoice', 'open') and not _po_has_payments(po) for po in pos)

def _po_has_payments(po):
    # if you add payments later; for now return False
    return False

@transaction.atomic
def cancel_purchase_request(pr, by_user, reason:str=''):
    if pr.status == 'cancelled':
        return pr  # idempotent

    # Basic permission ideas (adjust to your app):
    # - requestor can cancel own PR if not approved
    # - staff/admin can always cancel
    is_admin = getattr(by_user, 'is_staff', False) or by_user.is_superuser
    is_owner = (pr.requestor_id == by_user.id)

    if pr.status in ('draft', 'submitted'):
        if not (is_owner or is_admin):
            raise PermissionDenied("You can’t cancel this request.")
    elif pr.status == 'approved':
        if not is_admin:
            raise PermissionDenied("Only admin can cancel an approved request.")
        if not _all_pos_cancellable(pr):
            raise ValidationError("Cancel all related POs (or reverse payments) before cancelling this request.")
    elif pr.status == 'rejected':
        if not (is_owner or is_admin):
            raise PermissionDenied("You can’t cancel this request.")
    else:
        # unknown status safety
        raise ValidationError(f"Cannot cancel PR in status '{pr.status}'.")

    # 1) If in approval, mark workflow as cancelled/closed
    wf = getattr(pr, 'approval_workflow', None)
    if wf and not getattr(wf, 'is_complete', False):
        # you may want flags on workflow model
        wf.is_cancelled = True
        if hasattr(wf, 'cancelled_at'):
            wf.cancelled_at = timezone.now()
        wf.save(update_fields=[f for f in ['is_cancelled','cancelled_at'] if hasattr(wf, f)])

    # 2) Cancel POs if any (and if your rule allows)
    for po in pr.purchase_orders.all():
        # Guard: if PO has payments/shipments, you should block earlier
        po.status = 'cancelled'
        po.save(update_fields=['status'])

    # 3) Finally cancel PR
    pr.status = 'cancelled'
    pr.cancelled_at = timezone.now()
    pr.cancelled_by = by_user
    pr.cancellation_reason = (reason or '').strip()
    pr.save(update_fields=['status','cancelled_at','cancelled_by','cancellation_reason'])

    return pr