"""
Supplier rating computation & cache maintenance.

The Supplier rating cache (rating_score, rating_count, on_time_delivery_pct,
last_evaluated_at) is denormalized so the supplier list can sort/filter on it
without per-request aggregation. It is ONLY written here, and ONLY via
Supplier.objects.filter(pk=...).update(...) — a plain .save() would risk the
app's known post_save signal loops. Recompute is always triggered by an explicit
call (typically wrapped in transaction.on_commit), never a signal.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count
from django.utils import timezone

from .models import Supplier, SupplierEvaluation, PurchaseOrderLine

# Weights for the human criteria. Simplest thing that works; promote to settings
# if these ever need to be configurable per organization.
RATING_WEIGHTS = {
    'quality': Decimal('0.35'),
    'delivery': Decimal('0.30'),
    'price': Decimal('0.20'),
    'service': Decimal('0.15'),
}

# FK path from a PurchaseOrderLine to the planning item the warehouse marks as
# delivered (blue-app POST /planning/items/{id}/mark_delivered/).
_PI = 'purchase_request_item__planning_request_item'


def compute_composite(quality, delivery, price, service) -> Decimal:
    """Weighted 0–5 blend of the four human criteria, rounded to 2 dp."""
    total = (RATING_WEIGHTS['quality'] * Decimal(quality)
             + RATING_WEIGHTS['delivery'] * Decimal(delivery)
             + RATING_WEIGHTS['price'] * Decimal(price)
             + RATING_WEIGHTS['service'] * Decimal(service))
    return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _compute_on_time_pct(supplier_id):
    """
    Objective on-time-delivery percentage for a supplier.

    Promised date = (po.ordered_at or po.created_at) + line.delivery_days.
    Actual date   = the linked PlanningRequestItem.delivered_at.
    On-time       = actual.date() <= promised.date().

    Excluded from the ratio:
      - cancelled POs,
      - lines with no delivery_days SLA,
      - lines whose planning item is not yet delivered,
      - items satisfied from stock (quantity_from_inventory >= quantity), which
        are warehouse issues, not supplier deliveries.

    Returns None when there is nothing to measure (renders as "—" in the UI).
    """
    rows = (
        PurchaseOrderLine.objects
        .filter(po__supplier_id=supplier_id, delivery_days__isnull=False)
        .exclude(po__status='cancelled')
        .values(
            'delivery_days', 'po__ordered_at', 'po__created_at',
            f'{_PI}__is_delivered', f'{_PI}__delivered_at',
            f'{_PI}__quantity', f'{_PI}__quantity_from_inventory',
        )
    )

    total = 0
    on_time = 0
    for r in rows:
        if not r[f'{_PI}__is_delivered'] or not r[f'{_PI}__delivered_at']:
            continue
        qty = r[f'{_PI}__quantity'] or Decimal('0')
        from_inv = r[f'{_PI}__quantity_from_inventory'] or Decimal('0')
        if from_inv >= qty:
            continue  # fulfilled from stock, not by the supplier
        base = r['po__ordered_at'] or r['po__created_at']
        if not base:
            continue
        total += 1
        expected = (base + timedelta(days=r['delivery_days'])).date()
        if r[f'{_PI}__delivered_at'].date() <= expected:
            on_time += 1

    if total == 0:
        return None
    return (Decimal(on_time) / Decimal(total) * 100).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )


def recompute_supplier_rating(supplier_id) -> None:
    """
    Recompute and persist the full rating cache for one supplier.

    Single source of truth for the four cached columns. Writes with .update() so
    it can never re-fire post_save. Safe to call redundantly and from
    transaction.on_commit.
    """
    agg = (
        SupplierEvaluation.objects
        .filter(supplier_id=supplier_id)
        .exclude(purchase_order__status='cancelled')
        .aggregate(avg=Avg('composite_score'), n=Count('id'))
    )
    score = agg['avg']
    if score is not None:
        score = Decimal(score).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    count = agg['n'] or 0

    Supplier.objects.filter(pk=supplier_id).update(
        rating_score=score,
        rating_count=count,
        on_time_delivery_pct=_compute_on_time_pct(supplier_id),
        last_evaluated_at=timezone.now() if count else None,
    )
