# services/po_from_recommended.py
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError
from datetime import timedelta
from django.db.models import F


from procurement.reports.common import extract_rates, get_fallback_rates, to_eur

from .models import PurchaseOrder, PurchaseOrderLine, ItemOffer, PaymentTerms, PaymentSchedule, PurchaseOrderLineAllocation, Supplier

Q2 = lambda x: (Decimal(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def restore_planning_request_status(pr):
    """
    Restore planning request status when a purchase request is rejected or cancelled.

    This function checks all planning request items linked to the given purchase request
    and reverts their planning request status from 'converted' or 'completed' back to 'ready'
    if they are no longer in any active (non-rejected/non-cancelled) purchase requests.
    """
    from planning.models import PlanningRequest

    # Get all unique planning requests from this PR's items
    planning_requests = set()
    for item in pr.planning_request_items.all():
        if item.planning_request:
            planning_requests.add(item.planning_request)

    # Check each planning request and restore status if needed
    for planning_request in planning_requests:
        # Only process if status is 'converted' or 'completed'
        if planning_request.status not in ['converted', 'completed']:
            continue

        # Check if any item from this planning request is still in an active PR
        has_active_pr = False
        for pr_item in planning_request.items.all():
            # Only check items that need to be purchased
            if pr_item.quantity_to_purchase > 0:
                # Check if this item is in any active purchase request (not rejected or cancelled)
                active_prs = pr_item.purchase_requests.exclude(
                    status__in=['rejected', 'cancelled']
                )
                if active_prs.exists():
                    has_active_pr = True
                    break

        # If no items are in active PRs, restore status to 'ready'
        if not has_active_pr:
            planning_request.status = 'ready'
            planning_request.converted_at = None
            planning_request.completed_at = None
            planning_request.save(update_fields=['status', 'converted_at', 'completed_at'])


@transaction.atomic
def create_pos_from_recommended(pr):
    if pr.purchase_orders.exists():
        return []

    rec_offers = (
        ItemOffer.objects
        .select_related('purchase_request_item', 'supplier_offer', 'supplier_offer__supplier')
        .prefetch_related('purchase_request_item__allocations')
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
        # ✅ If supplier is DBS, don't create a PO — just increment DBS usage.
        if getattr(supplier, 'has_dbs', False):
            # ---- NET total (no tax). If you want GROSS, see note below. ----
            total_net = sum(
                Q2(io.purchase_request_item.quantity * io.unit_price)
                for io in item_offers
            )
            rate = (so.tax_rate or getattr(supplier, 'default_tax_rate', Decimal('0'))) / Decimal('100')
            total_gross = Q2(total_net * (Decimal('1') + rate))

            # Optional: normalize to a single currency for DBS tracking
            # Assuming supplier keeps DBS in its default currency or so.currency
            dbs_ccy = getattr(supplier, "dbs_currency", None) or (so.currency or getattr(supplier, "default_currency", "TRY"))

            # Use PR snapshot rates for consistency (same as your PO logic)
            pr_rates = extract_rates(getattr(pr, "currency_rates_snapshot", {}) or {})
            # Convert the batch total to the DBS currency (here I show TRY/EUR example using your to_eur;
            # if you have a to_currency() helper, swap it in)
            if dbs_ccy == "EUR":
                total_for_dbs = to_eur(total_gross, (so.currency or "TRY"), pr_rates, get_fallback_rates()) or Decimal("0.00")
            else:
                # If you store DBS in TRY (common), you might want a to_try(...) helper.
                # As a simple fallback, if currencies match, no conversion:
                total_for_dbs = total_gross if (so.currency or "TRY") == dbs_ccy else total_gross  # TODO: convert if needed

            # Atomic increment to avoid race conditions
            Supplier.objects.filter(pk=supplier.pk).update(dbs_used=F('dbs_used') + total_for_dbs)

            # Skip the rest for DBS suppliers
            continue

        po = PurchaseOrder.objects.create(
            pr=pr,
            supplier_offer=so,
            supplier=supplier,
            currency=(so.currency or supplier.default_currency or 'TRY'),
            priority=pr.priority,
            status='awaiting_payment',
            tax_rate=(so.tax_rate or getattr(supplier, 'default_tax_rate', Decimal('0.00')) or Decimal('0.00')),
        )

        for io in item_offers:
            pri = io.purchase_request_item
            qty = pri.quantity
            unit = io.unit_price
            total = Q2(qty * unit)

            line = PurchaseOrderLine.objects.create(
                po=po,
                item_offer=io,
                purchase_request_item=pri,
                quantity=qty,
                unit_price=unit,
                total_price=total,
                delivery_days=io.delivery_days,
                item_description=pri.item_description or '',
                notes=io.notes or '',
            )

            # ---- COPY ALLOCATIONS FROM PR ITEM ----
            pr_allocs = list(pri.allocations.all())
            if pr_allocs:
                to_create = []
                running = Decimal('0.00')
                for a in pr_allocs:
                    a_amount = Q2(a.quantity * unit)
                    running += a_amount
                    to_create.append(PurchaseOrderLineAllocation(
                        po_line=line,
                        job_no=a.job_no,
                        quantity=a.quantity,
                        amount=a_amount,
                    ))
                PurchaseOrderLineAllocation.objects.bulk_create(to_create)
                drift = Q2(total - running)
                if drift != Decimal('0.00'):
                    last = line.allocations.order_by('id').last()
                    last.amount = Q2(last.amount + drift)
                    last.save(update_fields=['amount'])
            elif pri.job_no:
                PurchaseOrderLineAllocation.objects.create(
                    po_line=line,
                    job_no=pri.job_no,
                    quantity=line.quantity,
                    amount=line.total_price,
                )

        # Now recompute NET + TAX; TAX from immutable po.tax_rate
        po.recompute_totals()

        # Create schedules (no tax fields) and compute due dates
        generate_payment_schedule_for_po(po, terms=so.payment_terms)
        # Optional: lock tax_rate now (policy)
        # po.lock_tax_rate()  # if you add such a method/flag
        recompute_payment_schedule_due_dates(po, save=True)
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

    if pr.status in ('submitted'):
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

    # 4) Restore planning request status if applicable
    restore_planning_request_status(pr)

    return pr

def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

@transaction.atomic
def generate_payment_schedule_for_po(po, terms: PaymentTerms | None = None):
    # idempotent
    if po.payment_schedules.exists():
        return list(po.payment_schedules.all())

    # pick terms: supplier default → "advance_100" fallback
    if terms is None:
        terms = getattr(po.supplier, "default_payment_terms", None)
    if terms is None:
        terms = PaymentTerms.objects.filter(code="advance_100", active=True).first()

    # last resort: create a temporary 100% peşin
    if terms is None:
        terms = PaymentTerms.objects.create(
            name="100% Peşin (Oto)",
            code=f"advance_100_auto_{timezone.now().strftime('%Y%m%d%H%M%S')}",
            default_lines=[{"percentage": 100.00, "label": "Peşin", "basis": "immediate", "offset_days": 0}],
            is_custom=True,
            active=True
        )    

    lines = terms.default_lines or [{"percentage": 100.00, "label": "Peşin", "basis": "immediate", "offset_days": 0}]
    pct_sum = sum((l.get("percentage") or 0) for l in lines)
    if round(pct_sum, 2) != 100.00:
        raise ValueError(f"PaymentTerms '{terms.name}' toplam %100 olmalı (şu an {pct_sum}).")

    total = po.total_amount
    created = []
    running = Decimal("0.00")
    for idx, line in enumerate(lines, start=1):
        pct = Decimal(str(line.get("percentage", 0)))
        amount = _q(total * pct / Decimal("100"))
        running += amount
        ps = PaymentSchedule.objects.create(
            purchase_order=po,
            payment_terms=terms,
            sequence=idx,
            label=line.get("label", ""),
            basis=line.get("basis", "custom"),
            offset_days=line.get("offset_days"),
            percentage=pct,
            amount=amount,
            currency=po.currency,
            due_date=None,  # hesaplanacak (fatura/teslim tarihi girilince)
        )
        created.append(ps)

    # rounding drift fix
    drift = _q(total - running)
    if drift != Decimal("0.00"):
        last = created[-1]
        last.amount = _q(last.amount + drift)
        last.save(update_fields=["amount"])

    return created

def _as_date(value):
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value

def _plus_days(base_date, days: int):
    if base_date is None:
        return None
    return base_date + timedelta(days=int(days or 0))

def _get_max_delivery_days(po) -> int:
    """
    Max snapshot delivery_days among PO lines.
    """
    max_days = 0
    for line in po.lines.all():
        dd = line.delivery_days
        if dd is not None and dd > max_days:
            max_days = dd
    return max_days

def _get_advance_schedule(po):
    """
    First schedule with basis=='immediate' by sequence, or None.
    """
    adv = None
    for s in po.payment_schedules.all():
        if s.basis == "immediate":
            if adv is None or s.sequence < adv.sequence:
                adv = s
    return adv

def recompute_payment_schedule_due_dates(po, save=True):
    """
    Rules:
      immediate            -> pr.needed_date - max_delivery_days
      on_delivery          -> (advance.paid_at OR advance.due_date OR po.created_at) + max_delivery_days
      after_invoice        -> (advance.paid_at OR advance.due_date OR po.created_at) + offset_days
      after_delivery       -> (advance.paid_at OR advance.due_date OR po.created_at) + max_delivery_days + offset_days
      custom               -> same as after_invoice (unless you later define otherwise)
    """
    po_created   = _as_date(getattr(po, "created_at", None))
    pr_needed    = _as_date(getattr(getattr(po, "pr", None), "needed_date", None))
    if pr_needed is None:
        # With your constraint, this should never happen. Raise to catch data issues early.
        raise ValueError("PurchaseRequest.needed_date must be set before computing payment schedule due dates.")

    max_dd       = _get_max_delivery_days(po)
    schedules    = list(po.payment_schedules.all().order_by("sequence"))
    advance      = _get_advance_schedule(po)
    changed      = []

    # ---------- PASS 1: compute advance (immediate) ----------
    adv_due = None
    adv_base_paid = None
    if advance:
        # Always: needed_date - max_delivery_days (no fallback)
        new_due = _plus_days(pr_needed, -max_dd)
        if advance.due_date != new_due:
            advance.due_date = new_due
            changed.append(advance)
        adv_due = advance.due_date  # planned (always present)
        adv_base_paid = _as_date(advance.paid_at) if advance.is_paid else None

    # Helper: base date other schedules use
    def _dependent_base():
        if advance:
            # paid wins; else planned
            return adv_base_paid or adv_due
        # no advance → base on PO creation date
        return po_created

    # ---------- PASS 2: compute others ----------
    for s in schedules:
        if s is advance:
            continue

        basis  = s.basis or "custom"
        offset = s.offset_days or 0
        base   = _dependent_base()
        new_due = None

        if basis == "on_delivery":
            new_due = _plus_days(base, max_dd) if base is not None else None

        elif basis == "after_invoice":
            new_due = _plus_days(base, offset) if base is not None else None

        elif basis == "after_delivery":
            new_due = _plus_days(base, max_dd + offset) if base is not None else None

        else:
            # 'custom' mirrors after_invoice by default
            new_due = _plus_days(base, offset) if base is not None else None

        if s.due_date != new_due:
            s.due_date = new_due
            changed.append(s)

    if save and changed:
        for s in changed:
            s.save(update_fields=["due_date"])
    return changed

def compute_vat_carry_map(po):
    """
    Returns:
      {
        'by_id': { schedule_id: {'base_tax': Decimal, 'effective_tax_due': Decimal} },
        'tax_outstanding': Decimal,  # sum of effective tax for UNPAID schedules
      }
    Enforces the algorithm:
      - base_tax = amount * po.tax_rate
      - carry propagates through paid-without-tax schedules
      - VAT parks on first UNPAID schedule
    This function assumes endpoint prevented “last unpaid, net-only” state.
    """
    rate = (po.tax_rate or Decimal('0')) / Decimal('100')
    schedules = list(po.payment_schedules.all().order_by('sequence'))

    by_id = {}
    carry = Decimal('0.00')
    tax_outstanding = Decimal('0.00')

    for s in schedules:
        base_tax = Q2(Decimal(s.amount) * rate)
        effective_before = Q2(base_tax + carry)

        if s.is_paid:
            if s.paid_with_tax:
                eff_due = Decimal('0.00')
                carry = Decimal('0.00')
            else:
                # net-only → push VAT to next
                eff_due = Decimal('0.00')
                carry = effective_before
        else:
            # unpaid → VAT parks here; reset carry
            eff_due = effective_before
            carry = Decimal('0.00')
            tax_outstanding += eff_due

        by_id[s.id] = {'base_tax': base_tax, 'effective_tax_due': eff_due}

    # Safety note: if carry > 0 here, endpoint invariants were violated (last unpaid paid net-only).
    return {'by_id': by_id, 'tax_outstanding': Q2(tax_outstanding)}