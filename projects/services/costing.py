from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce


q2 = lambda x: Decimal(x).quantize(Decimal('0.01'))  # noqa: E731


@lru_cache(maxsize=128)
def _fetch_rates(on_date: date) -> dict:
    """
    Return the rates dict from the CurrencyRateSnapshot nearest to on_date.
    Cached per date — historical rates never change, and 'today' becomes a
    different cache key each calendar day so it always fetches fresh data.
    """
    from core.models import CurrencyRateSnapshot

    snap = (
        CurrencyRateSnapshot.objects
        .filter(date__lte=on_date)
        .order_by('-date')
        .values('rates')
        .first()
    )
    if snap is None:
        snap = CurrencyRateSnapshot.objects.order_by('date').values('rates').first()
    return snap['rates'] if snap else {}


def convert_to_eur(amount: Decimal, currency: str, on_date: date) -> Decimal:
    """
    Convert an amount in any supported currency to EUR using CurrencyRateSnapshot.
    Uses the last snapshot on/before on_date (or earliest if none found before).
    Returns Decimal('0.00') if no snapshot is available or rate is missing.
    """
    if not amount:
        return Decimal('0.00')
    amount = Decimal(str(amount))
    if currency == 'EUR':
        return amount

    rates = _fetch_rates(on_date)  # single DB hit per date, then cached
    if not rates:
        return Decimal('0.00')

    if currency == 'TRY':
        eur_rate = Decimal(str(rates.get('EUR', 0)))
        if eur_rate == 0:
            return Decimal('0.00')
        return q2(amount * eur_rate)

    # Cross-rate via TRY: 1 src_currency = (rates['EUR'] / rates[src]) EUR
    eur_rate = Decimal(str(rates.get('EUR', 0)))
    src_rate = Decimal(str(rates.get(currency, 0)))
    if src_rate == 0 or eur_rate == 0:
        return Decimal('0.00')
    return q2(amount * (eur_rate / src_rate))


def _decimal_str(value: Decimal) -> str:
    return str(q2(value or Decimal('0.00')))


def offer_phase_shares(offer) -> dict:
    """
    Map of ``offer_item_id -> Decimal`` fractional share of the offer's
    line-item total, used to pro-rate the offer's current_price across the
    phase job orders created from it (Option 3 pricing).

    Root items' shares sum to 1.0; child items carry their own leaf share so a
    child job order linked to a child item is pro-rated too. Returns ``{}`` when
    the offer line total is zero or undeterminable (caller falls back to the
    whole-offer price).

    Uses ``offer.items.all()`` (one query, or the prefetch cache when available)
    and primes each item's subtotal caches so no per-item DB hits occur.
    """
    items = list(offer.items.all())
    children_by_parent: dict = {}
    for it in items:
        if it.parent_id is not None:
            children_by_parent.setdefault(it.parent_id, []).append(it)
    for it in items:
        it._offer_cache = offer
        it._children_cache = children_by_parent.get(it.id, [])

    total = Decimal('0.00')
    for it in items:
        if it.parent_id is None:
            sub = it.subtotal
            if sub:
                total += sub
    if total <= 0:
        return {}

    shares: dict = {}
    for it in items:
        sub = it.subtotal
        if sub is not None:
            shares[it.id] = Decimal(sub) / total
    return shares


def phase_share_amount(job_order, offer_price_amount: Decimal):
    """
    Return job_order's pro-rated slice of ``offer_price_amount`` (in the offer's
    currency) based on its linked phase item, or ``None`` when the job order is
    not phase-linked or the share cannot be computed.
    """
    item_id = getattr(job_order, 'source_offer_item_id', None)
    offer = getattr(job_order, 'source_offer', None)
    if not item_id or offer is None:
        return None
    share = offer_phase_shares(offer).get(item_id)
    if share is None:
        return None
    return offer_price_amount * share


def _effective_selling_price(job_order, summary=None) -> dict:
    """
    Return the best known selling price converted to EUR.

    Sales offer current price is preferred because converted job orders keep the
    commercial source there. The manual summary price remains the fallback.
    """
    today = date.today()
    offer_price = None
    if getattr(job_order, 'source_offer_id', None):
        offer_price = job_order.source_offer.current_price

    if offer_price:
        original_currency = offer_price.currency
        phase_amount = phase_share_amount(job_order, offer_price.amount)
        if phase_amount is not None:
            original_amount = phase_amount
            source = 'sales_offer_phase_share'
        else:
            original_amount = offer_price.amount
            source = 'sales_offer_current_price'
    elif summary:
        original_amount = summary.selling_price
        original_currency = summary.selling_price_currency
        source = 'cost_summary'
    else:
        original_amount = Decimal('0.00')
        original_currency = 'EUR'
        source = 'none'

    amount_eur = convert_to_eur(original_amount, original_currency, today)
    return {
        'amount_eur': _decimal_str(amount_eur),
        'currency': 'EUR',
        'original_amount': _decimal_str(original_amount),
        'original_currency': original_currency,
        'source': source,
    }


def _planning_items_with_price_annotations(job_no: str):
    from django.db.models import OuterRef, Prefetch, Subquery
    from planning.models import PlanningRequestItem
    from procurement.models import PurchaseOrderLine, PurchaseRequestItem, ItemOffer

    pol_m2m_base = PurchaseOrderLine.objects.filter(
        purchase_request_item__purchase_request__planning_request_items=OuterRef('pk'),
        purchase_request_item__item_id=OuterRef('item_id'),
    ).exclude(
        Q(purchase_request_item__purchase_request__status='cancelled') |
        Q(po__status='cancelled')
    ).order_by('-po__ordered_at', '-po__created_at', '-id')

    pol_hist_base = PurchaseOrderLine.objects.filter(
        purchase_request_item__item_id=OuterRef('item_id'),
    ).exclude(
        Q(purchase_request_item__purchase_request__status='cancelled') |
        Q(po__status='cancelled')
    ).order_by('-po__ordered_at', '-po__created_at', '-id')

    return (
        PlanningRequestItem.objects
        .filter(job_no=job_no)
        .exclude(planning_request__status='cancelled')
        .select_related('item')
        .prefetch_related(
            Prefetch(
                'purchase_request_items',
                queryset=PurchaseRequestItem.objects.select_related('purchase_request'),
            ),
            Prefetch(
                'purchase_request_items__po_lines',
                queryset=PurchaseOrderLine.objects.select_related('po').order_by('-id'),
            ),
            Prefetch(
                'purchase_request_items__offers',
                queryset=ItemOffer.objects.select_related('supplier_offer').order_by('-id'),
            ),
        )
        .annotate(
            _t2_price=Subquery(pol_m2m_base.values('unit_price')[:1]),
            _t2_currency=Subquery(pol_m2m_base.values('po__currency')[:1]),
            _t2_tax=Subquery(pol_m2m_base.values('po__tax_rate')[:1]),
            _t2_date=Subquery(
                pol_m2m_base.annotate(_ref_date=Coalesce('po__ordered_at', 'po__created_at'))
                .values('_ref_date')[:1]
            ),
            _t5_price=Subquery(pol_hist_base.values('unit_price')[:1]),
            _t5_currency=Subquery(pol_hist_base.values('po__currency')[:1]),
            _t5_tax=Subquery(pol_hist_base.values('po__tax_rate')[:1]),
            _t5_date=Subquery(
                pol_hist_base.annotate(_ref_date=Coalesce('po__ordered_at', 'po__created_at'))
                .values('_ref_date')[:1]
            ),
        )
        .order_by('id')
    )


def _procurement_line_to_material_dict(pl) -> dict:
    return {
        'procurement_line_id': pl.pk,
        'planning_request_item': pl.planning_request_item_id,
        'item': pl.item_id,
        'item_code': pl.item.code if pl.item else None,
        'item_name': pl.item.name if pl.item else (pl.item_description or None),
        'item_unit': pl.item.unit if pl.item else None,
        'quantity': str(pl.quantity),
        'unit_price_eur': _decimal_str(pl.unit_price),
        'original_unit_price': _decimal_str(pl.unit_price),
        'original_currency': 'EUR',
        'amount_eur': _decimal_str(pl.amount_eur),
        'price_source': 'procurement_line',
        'price_date': pl.created_at.date().isoformat() if pl.created_at else None,
    }


def _resolved_price_to_material_dict(pri, price, quantity, unit_price, amount) -> dict:
    row = {
        'procurement_line_id': None,
        'planning_request_item': pri.pk,
        'item': pri.item_id,
        'item_code': pri.item.code if pri.item else None,
        'item_name': pri.item.name if pri.item else None,
        'item_unit': pri.item.unit if pri.item else None,
        'quantity': str(quantity),
        'unit_price_eur': _decimal_str(unit_price),
        'amount_eur': _decimal_str(amount),
        'price_source': price['price_source'] if price else 'none',
        'price_date': price['price_date'].isoformat() if price and price.get('price_date') else None,
    }
    if price:
        row['original_unit_price'] = _decimal_str(price['original_unit_price'])
        row['original_currency'] = price['original_currency']
    else:
        row['original_unit_price'] = _decimal_str(Decimal('0.00'))
        row['original_currency'] = None
    return row


def _estimate_material_cost(job_no: str) -> tuple[Decimal, list[dict]]:
    """
    Estimate full material cost from planning items.

    Saved procurement lines take precedence over price-resolution for the same
    planning item. Orphan procurement lines (no planning link) are included too.
    """
    from planning.price_utils import resolve_planning_item_price
    from projects.models import JobOrderProcurementLine

    procurement_by_pri: dict[int, list] = {}
    orphan_procurement_lines = []
    for pl in (
        JobOrderProcurementLine.objects
        .filter(job_order_id=job_no)
        .select_related('item')
        .order_by('order', 'id')
    ):
        if pl.planning_request_item_id:
            procurement_by_pri.setdefault(pl.planning_request_item_id, []).append(pl)
        else:
            orphan_procurement_lines.append(pl)

    total = Decimal('0.00')
    lines = []
    covered_pri_ids: set[int] = set()
    for pri in _planning_items_with_price_annotations(job_no):
        covered_pri_ids.add(pri.pk)
        saved_lines = procurement_by_pri.get(pri.pk)
        if saved_lines:
            for pl in saved_lines:
                amount = q2(pl.amount_eur)
                total += amount
                lines.append(_procurement_line_to_material_dict(pl))
            continue

        price = resolve_planning_item_price(pri)
        unit_price = price['unit_price_eur'] if price else Decimal('0.00')
        quantity = Decimal(str(pri.quantity or 0))
        amount = q2(quantity * unit_price)
        total += amount
        lines.append(_resolved_price_to_material_dict(pri, price, quantity, unit_price, amount))

    for pri_id, saved_lines in procurement_by_pri.items():
        if pri_id in covered_pri_ids:
            continue
        for pl in saved_lines:
            amount = q2(pl.amount_eur)
            total += amount
            lines.append(_procurement_line_to_material_dict(pl))

    for pl in orphan_procurement_lines:
        amount = q2(pl.amount_eur)
        total += amount
        lines.append(_procurement_line_to_material_dict(pl))

    return q2(total), lines


def _collect_estimated_material_items(job_order, items_out: list[dict]) -> Decimal:
    """Append own material lines (tagged with job_order) and recurse into children."""
    from projects.models import JobOrder

    own_total, own_lines = _estimate_material_cost(job_order.job_no)
    for line in own_lines:
        items_out.append({**line, 'job_order': job_order.job_no})
    rolled_up = own_total
    for child in JobOrder.objects.filter(parent_id=job_order.job_no).order_by('job_no'):
        rolled_up += _collect_estimated_material_items(child, items_out)
    return q2(rolled_up)


def build_estimated_material_breakdown(job_order) -> dict:
    """
    Line-level breakdown of estimated material cost for a job order tree.

    Each item row includes quantity, EUR unit price, amount, price source, and
    original price/currency when resolved from PO or offer data.
    """
    from projects.models import JobOrderCostSummary

    summary, _ = JobOrderCostSummary.objects.get_or_create(job_order=job_order)
    items: list[dict] = []
    lines_total = _collect_estimated_material_items(job_order, items)
    actual_material_cost = q2(summary.material_cost)
    estimated_material_cost = lines_total
    material_cost_floored = False
    if estimated_material_cost < actual_material_cost:
        estimated_material_cost = actual_material_cost
        material_cost_floored = True
    floor_adjustment = q2(estimated_material_cost - lines_total)

    return {
        'job_order': job_order.job_no,
        'currency': 'EUR',
        'items': items,
        'items_count': len(items),
        'lines_total': _decimal_str(lines_total),
        'estimated_material_cost': _decimal_str(estimated_material_cost),
        'actual_material_cost': _decimal_str(actual_material_cost),
        'floor_adjustment_eur': _decimal_str(floor_adjustment),
        'material_cost_floored_to_actual': material_cost_floored,
    }


def _historical_paint_rate_eur_per_kg(exclude_job_no: str) -> Decimal:
    from projects.models import JobOrderCostSummary

    rows = (
        JobOrderCostSummary.objects
        .filter(
            job_order__status='completed',
            paint_cost__gt=0,
            job_order__total_weight_kg__gt=0,
        )
        .exclude(job_order_id=exclude_job_no)
        .values_list('paint_cost', 'job_order__total_weight_kg')
    )
    total_cost = Decimal('0.00')
    total_weight = Decimal('0.00')
    for paint_cost, weight in rows:
        total_cost += Decimal(str(paint_cost or 0))
        total_weight += Decimal(str(weight or 0))
    if total_weight <= 0:
        return Decimal('0.00')
    return total_cost / total_weight


def _child_cost_summary_map(direct_children) -> dict:
    """JobOrderCostSummary keyed by job_no for direct children."""
    from projects.models import JobOrderCostSummary

    if not direct_children:
        return {}
    child_nos = [c.job_no for c in direct_children]
    result = {
        s.job_order_id: s
        for s in JobOrderCostSummary.objects.filter(job_order_id__in=child_nos)
    }
    for child in direct_children:
        if child.job_no not in result:
            result[child.job_no], _ = JobOrderCostSummary.objects.get_or_create(job_order=child)
    return result


def _own_rolled_up_component(parent_summary, field: str, child_summaries: list) -> Decimal:
    """
    Parent JobOrderCostSummary stores tree totals (own + direct children).
    Subtract direct children's rolled-up totals to recover this job's own amount.
    """
    own = Decimal(str(getattr(parent_summary, field) or 0))
    for cs in child_summaries:
        own -= Decimal(str(getattr(cs, field) or 0))
    return q2(own)


def build_job_cost_payload(job_order) -> dict:
    """
    Build the endpoint payload for current actual cost and estimated full cost.

    Actual values come from JobOrderCostSummary. Estimate is calculated from the
    current system state and projected to 100% progress where appropriate.
    """
    from subcontracting.models import SubcontractingAssignment
    from projects.models import JobOrder, JobOrderCostSummary, JobOrderDepartmentTask

    summary, _ = JobOrderCostSummary.objects.get_or_create(job_order=job_order)
    summary.job_order = job_order

    direct_children = list(
        JobOrder.objects.filter(parent_id=job_order.job_no).select_related('source_offer')
    )
    child_summary_map = _child_cost_summary_map(direct_children)
    child_summaries = [child_summary_map[c.job_no] for c in direct_children]

    total_weight = Decimal(str(job_order.total_weight_kg or 0))
    completion = Decimal(str(job_order.completion_percentage or 0))
    progress_ratio = completion / Decimal('100') if completion > 0 else Decimal('0')

    today = date.today()
    non_paint_assignments = list(
        SubcontractingAssignment.objects
        .filter(
            department_task__job_order_id=job_order.job_no,
            price_tier__isnull=False,
            is_retired=False,
        )
        .exclude(price_tier__tier_type='paint')
        .select_related('price_tier')
    )
    subcontractor_estimate = q2(sum(
        convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, today)
        for a in non_paint_assignments
    ))

    own_labor = _own_rolled_up_component(summary, 'labor_cost', child_summaries)
    labor_estimate = q2(
        own_labor / progress_ratio
        if progress_ratio > 0 and own_labor > 0
        else own_labor
    )

    has_painting = JobOrderDepartmentTask.objects.filter(
        job_order_id=job_order.job_no,
        task_type='painting',
    ).exclude(status='skipped').exists()
    historical_paint_rate = _historical_paint_rate_eur_per_kg(job_order.job_no)
    paint_assignments = []
    if has_painting and total_weight > 0 and historical_paint_rate > 0:
        paint_estimate = q2(historical_paint_rate * total_weight)
        paint_source = 'completed_job_orders_avg_eur_per_kg'
    else:
        paint_assignments = list(
            SubcontractingAssignment.objects.filter(
                department_task__job_order_id=job_order.job_no,
                price_tier__tier_type='paint',
                allocated_weight_kg__gt=0,
                is_retired=False,
            ).select_related('price_tier')
        )
        paint_estimate = q2(sum(
            convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, today)
            for a in paint_assignments
        ))
        paint_source = 'paint_assignment_at_100' if paint_estimate else 'none'
    paint_assignment_count = (
        len(paint_assignments)
        if paint_source == 'paint_assignment_at_100'
        else 0
    )

    paint_material_estimate = q2(
        convert_to_eur(summary.paint_material_rate * total_weight, 'TRY', today)
        if total_weight > 0 else Decimal('0.00')
    )
    employee_overhead_rate = Decimal(str(summary.employee_overhead_rate or Decimal('0.65')))
    employee_overhead_estimate = q2(labor_estimate * employee_overhead_rate)
    general_expenses_rate = Decimal(str(job_order.general_expenses_rate or 0))
    general_expenses_estimate = q2(
        general_expenses_rate * total_weight
        if (general_expenses_rate > 0 and total_weight > 0) else Decimal('0.00')
    )
    material_estimate, material_lines = _estimate_material_cost(job_order.job_no)

    estimated_components = {
        'subcontractor_cost': subcontractor_estimate,
        'labor_cost': labor_estimate,
        'paint_cost': paint_estimate,
        'paint_material_cost': paint_material_estimate,
        'employee_overhead_cost': employee_overhead_estimate,
        'qc_cost': _own_rolled_up_component(summary, 'qc_cost', child_summaries),
        'shipping_cost': _own_rolled_up_component(summary, 'shipping_cost', child_summaries),
        'general_expenses_cost': general_expenses_estimate,
        'material_cost': material_estimate,
    }

    own_qc = estimated_components['qc_cost']
    own_shipping = estimated_components['shipping_cost']

    child_payloads = []
    for child in direct_children:
        child_payload = build_job_cost_payload(child)
        child_payloads.append({
            'job_order': child.job_no,
            'estimated_total_cost': child_payload['estimated']['total_cost'],
            'actual_total_cost': child_payload['actual']['total_cost'],
        })
        for key in estimated_components:
            estimated_components[key] += Decimal(child_payload['estimated']['components'][key])

    # Material already committed (procurement lines) must not be below actual.
    actual_material_total = q2(summary.material_cost)
    material_cost_floored = False
    if estimated_components['material_cost'] < actual_material_total:
        estimated_components['material_cost'] = actual_material_total
        material_cost_floored = True

    estimated_total = q2(sum(estimated_components.values(), Decimal('0.00')))
    actual_components = {
        'labor_cost': summary.labor_cost,
        'material_cost': summary.material_cost,
        'subcontractor_cost': summary.subcontractor_cost,
        'paint_cost': summary.paint_cost,
        'paint_material_cost': summary.paint_material_cost,
        'employee_overhead_cost': summary.employee_overhead_cost,
        'qc_cost': summary.qc_cost,
        'shipping_cost': summary.shipping_cost,
        'general_expenses_cost': summary.general_expenses_cost,
        'other_cost': summary.other_cost,
    }

    selling_price = _effective_selling_price(job_order, summary)
    return {
        'job_order': job_order.job_no,
        'total_weight_kg': str(total_weight) if job_order.total_weight_kg is not None else None,
        'completion_pct': str(completion),
        'currency': 'EUR',
        'selling_price': selling_price['amount_eur'],
        'selling_price_currency': 'EUR',
        'selling_price_eur': selling_price['amount_eur'],
        'selling_price_effective': selling_price,
        'actual': {
            'currency': 'EUR',
            'total_cost': _decimal_str(summary.actual_total_cost),
            'components': {key: _decimal_str(value) for key, value in actual_components.items()},
        },
        'estimated': {
            'currency': 'EUR',
            'total_cost': _decimal_str(estimated_total),
            'components': {key: _decimal_str(value) for key, value in estimated_components.items()},
            'assumptions': {
                'labor_projected_from_completion_pct': str(completion),
                'own_labor_cost_eur': _decimal_str(own_labor),
                'own_qc_cost_eur': _decimal_str(own_qc),
                'own_shipping_cost_eur': _decimal_str(own_shipping),
                'employee_overhead_rate': str(employee_overhead_rate),
                'paint_cost_source': paint_source,
                'historical_paint_rate_eur_per_kg': _decimal_str(historical_paint_rate),
                'material_cost_floored_to_actual': material_cost_floored,
                'non_paint_assignment_count': len(non_paint_assignments),
                'paint_assignment_count': paint_assignment_count,
                'general_expenses_rate': str(general_expenses_rate),
            },
            'material_lines': material_lines,
            'children': child_payloads,
        },
        'editable': {
            'paint_material_rate': str(summary.paint_material_rate),
            'employee_overhead_rate': str(summary.employee_overhead_rate),
            'general_expenses_rate': str(general_expenses_rate),
            'cost_not_applicable': summary.cost_not_applicable,
        },
        'last_updated': summary.last_updated.isoformat() if summary.last_updated else None,
    }


_ESTIMATED_COMPONENT_ORDER = (
    'subcontractor_cost',
    'labor_cost',
    'paint_cost',
    'paint_material_cost',
    'employee_overhead_cost',
    'qc_cost',
    'shipping_cost',
    'general_expenses_cost',
    'material_cost',
)

_ESTIMATED_COMPONENT_LABELS = {
    'subcontractor_cost': 'Taşeron',
    'labor_cost': 'İşçilik',
    'paint_cost': 'Boya',
    'paint_material_cost': 'Boya Malzemesi',
    'employee_overhead_cost': 'Personel Genel Giderleri',
    'qc_cost': 'Kalite Kontrol',
    'shipping_cost': 'Sevkiyat',
    'general_expenses_cost': 'Genel Giderler',
    'material_cost': 'Malzeme',
}


def build_estimated_cost_breakdown(job_order) -> dict:
    """
    Human-readable breakdown of how estimated total cost is calculated for a job
    order tree (own job + rolled-up children).
    """
    payload = build_job_cost_payload(job_order)
    estimated = payload['estimated']
    assumptions = estimated['assumptions']
    components = estimated['components']
    actual_components = payload['actual']['components']
    children = estimated.get('children') or []
    material_breakdown = build_estimated_material_breakdown(job_order)

    completion = Decimal(str(payload.get('completion_pct') or 0))
    total_weight = Decimal(str(payload.get('total_weight_kg') or 0))
    editable = payload.get('editable') or {}
    paint_material_rate = Decimal(str(editable.get('paint_material_rate') or 0))
    employee_overhead_rate = Decimal(str(assumptions.get('employee_overhead_rate') or 0))

    child_note = ' Alt iş emri tahminleri bu kaleme dahil edilmiştir.' if children else ''

    def _detail(key, label, amount_eur, description, inputs=None):
        return {
            'key': key,
            'label': label,
            'amount_eur': amount_eur,
            'actual_amount_eur': actual_components.get(key, '0.00'),
            'description': description,
            'inputs': inputs or {},
        }

    component_details = []

    component_details.append(_detail(
        'subcontractor_cost',
        _ESTIMATED_COMPONENT_LABELS['subcontractor_cost'],
        components['subcontractor_cost'],
        (
            'Boya hariç taşeron atamaları: tahsis edilen ağırlık (kg) × birim fiyat, '
            'para birimi EUR\'a çevrilir.'
            + child_note
        ),
        {
            'assignment_count': assumptions.get('non_paint_assignment_count'),
        },
    ))

    own_labor = Decimal(str(assumptions.get('own_labor_cost_eur') or 0))
    actual_labor = Decimal(str(actual_components.get('labor_cost') or 0))
    if completion > 0 and own_labor > 0:
        labor_desc = (
            f'Bu iş emrinin kendi işçilik maliyeti ({_decimal_str(own_labor)} EUR), '
            f'%{_decimal_str(completion)} tamamlanma oranına göre %100\'e ölçeklenir.'
            + child_note
        )
        labor_inputs = {
            'own_labor_cost_eur': _decimal_str(own_labor),
            'actual_labor_cost_eur': _decimal_str(actual_labor),
            'completion_pct': str(completion),
        }
    else:
        labor_desc = (
            'Bu iş emrinin kendi işçilik maliyeti kullanılır (tamamlanma %0 veya işçilik kaydı yok).'
            + child_note
        )
        labor_inputs = {
            'own_labor_cost_eur': _decimal_str(own_labor),
            'actual_labor_cost_eur': _decimal_str(actual_labor),
            'completion_pct': str(completion),
        }
    component_details.append(_detail(
        'labor_cost',
        _ESTIMATED_COMPONENT_LABELS['labor_cost'],
        components['labor_cost'],
        labor_desc,
        labor_inputs,
    ))

    paint_source = assumptions.get('paint_cost_source') or 'none'
    if paint_source == 'completed_job_orders_avg_eur_per_kg':
        paint_desc = (
            f'Tamamlanan iş emirlerinden hesaplanan ortalama boya maliyeti '
            f'({_decimal_str(assumptions.get("historical_paint_rate_eur_per_kg"))} EUR/kg) × '
            f'toplam ağırlık ({_decimal_str(total_weight)} kg).'
            + child_note
        )
        paint_inputs = {
            'historical_paint_rate_eur_per_kg': assumptions.get('historical_paint_rate_eur_per_kg'),
            'total_weight_kg': payload.get('total_weight_kg'),
            'paint_cost_source': paint_source,
        }
    elif paint_source == 'paint_assignment_at_100':
        paint_desc = (
            'Boya taşeron atamaları: tahsis edilen ağırlık × birim fiyat (EUR\'a çevrilir).'
            + child_note
        )
        paint_inputs = {
            'assignment_count': assumptions.get('paint_assignment_count'),
            'paint_cost_source': paint_source,
        }
    else:
        paint_desc = 'Boya maliyeti tahmini tanımlı değil (boya görevi yok veya atama/fiyat yok).' + child_note
        paint_inputs = {'paint_cost_source': paint_source}
    component_details.append(_detail(
        'paint_cost',
        _ESTIMATED_COMPONENT_LABELS['paint_cost'],
        components['paint_cost'],
        paint_desc,
        paint_inputs,
    ))

    component_details.append(_detail(
        'paint_material_cost',
        _ESTIMATED_COMPONENT_LABELS['paint_material_cost'],
        components['paint_material_cost'],
        (
            f'Boya malzemesi oranı ({_decimal_str(paint_material_rate)} TRY/kg) × '
            f'toplam ağırlık ({_decimal_str(total_weight)} kg), EUR\'a çevrilir.'
            + child_note
        ),
        {
            'paint_material_rate_try_per_kg': str(paint_material_rate),
            'total_weight_kg': payload.get('total_weight_kg'),
        },
    ))

    component_details.append(_detail(
        'employee_overhead_cost',
        _ESTIMATED_COMPONENT_LABELS['employee_overhead_cost'],
        components['employee_overhead_cost'],
        (
            f'Tahmini işçilik ({components["labor_cost"]} EUR) × personel genel gider oranı '
            f'({_decimal_str(employee_overhead_rate)}).'
            + child_note
        ),
        {
            'estimated_labor_cost_eur': components['labor_cost'],
            'employee_overhead_rate': str(employee_overhead_rate),
        },
    ))

    own_qc = assumptions.get('own_qc_cost_eur')
    qc_desc = (
        f'Bu iş emrinin kayıtlı KK satırları ({own_qc} EUR, tahmin = mevcut).'
        if children else
        'Kayıtlı kalite kontrol maliyet satırları toplamı (tahmin = mevcut).'
    ) + child_note
    component_details.append(_detail(
        'qc_cost',
        _ESTIMATED_COMPONENT_LABELS['qc_cost'],
        components['qc_cost'],
        qc_desc,
        {
            'own_qc_cost_eur': own_qc,
            'actual_qc_cost_eur': actual_components.get('qc_cost'),
        },
    ))

    own_shipping = assumptions.get('own_shipping_cost_eur')
    shipping_desc = (
        f'Bu iş emrinin kayıtlı sevkiyat satırları ({own_shipping} EUR, tahmin = mevcut).'
        if children else
        'Kayıtlı sevkiyat maliyet satırları toplamı (tahmin = mevcut).'
    ) + child_note
    component_details.append(_detail(
        'shipping_cost',
        _ESTIMATED_COMPONENT_LABELS['shipping_cost'],
        components['shipping_cost'],
        shipping_desc,
        {
            'own_shipping_cost_eur': own_shipping,
            'actual_shipping_cost_eur': actual_components.get('shipping_cost'),
        },
    ))

    general_expenses_rate = Decimal(str(assumptions.get('general_expenses_rate') or 0))
    component_details.append(_detail(
        'general_expenses_cost',
        _ESTIMATED_COMPONENT_LABELS['general_expenses_cost'],
        components['general_expenses_cost'],
        (
            f'Genel gider oranı ({_decimal_str(general_expenses_rate)}) × '
            f'toplam ağırlık ({_decimal_str(total_weight)} kg).'
            + child_note
        ),
        {
            'general_expenses_rate': str(general_expenses_rate),
            'total_weight_kg': payload.get('total_weight_kg'),
        },
    ))

    material_desc = (
        'Planlama kalemleri ve kayıtlı satın alma satırlarından hesaplanır; '
        'kayıtlı satırlar planlama fiyat çözümlemesine göre önceliklidir.'
        + child_note
    )
    if assumptions.get('material_cost_floored_to_actual'):
        material_desc += (
            f' Satır toplamı ({material_breakdown["lines_total"]} EUR) mevcut malzeme maliyetinin '
            f'({material_breakdown["actual_material_cost"]} EUR) altında kaldığı için tahmin bu seviyeye yükseltildi.'
        )
    component_details.append(_detail(
        'material_cost',
        _ESTIMATED_COMPONENT_LABELS['material_cost'],
        components['material_cost'],
        material_desc,
        {
            'lines_total_eur': material_breakdown.get('lines_total'),
            'actual_material_cost_eur': material_breakdown.get('actual_material_cost'),
            'material_cost_floored_to_actual': assumptions.get('material_cost_floored_to_actual'),
            'items_count': material_breakdown.get('items_count'),
        },
    ))

    assumption_notes = []
    if completion > 0 and own_labor > 0:
        assumption_notes.append(
            f'İşçilik tahmini, bu iş emrinin kendi maliyeti ve mevcut ilerleme '
            f'(%{float(completion):.2f}) üzerinden %100\'e ölçeklenmiştir.'
        )
    assumption_notes.append(
        f'Personel genel gider oranı: {float(employee_overhead_rate):.4f}'
    )
    if paint_source == 'completed_job_orders_avg_eur_per_kg':
        assumption_notes.append(
            'Boya maliyeti kaynağı: tamamlanan iş emirleri ortalaması (€/kg).'
        )
    elif paint_source == 'paint_assignment_at_100':
        assumption_notes.append('Boya maliyeti kaynağı: boya taşeron ataması.')
    if paint_material_rate > 0:
        assumption_notes.append(f'Boya malzemesi oranı: {paint_material_rate} TRY/kg.')
    if general_expenses_rate > 0:
        assumption_notes.append(
            f'Genel gider oranı: {float(general_expenses_rate):.4f} (ağırlık × oran).'
        )
    if assumptions.get('material_cost_floored_to_actual'):
        assumption_notes.append(
            'Malzeme tahmini, mevcut kayıtlı maliyetin altına düşmeyecek şekilde ayarlandı.'
        )

    ordered_details = sorted(
        component_details,
        key=lambda row: (
            _ESTIMATED_COMPONENT_ORDER.index(row['key'])
            if row['key'] in _ESTIMATED_COMPONENT_ORDER
            else 99
        ),
    )

    return {
        'job_order': payload['job_order'],
        'currency': payload.get('currency') or 'EUR',
        'total_cost': estimated['total_cost'],
        'actual_total_cost': payload['actual']['total_cost'],
        'completion_pct': payload.get('completion_pct'),
        'total_weight_kg': payload.get('total_weight_kg'),
        'components': ordered_details,
        'assumptions': assumption_notes,
        'children': children,
        'material_breakdown': material_breakdown,
        'last_updated': payload.get('last_updated'),
    }


def _store_estimated_total_cost(job_no: str) -> None:
    """Persist projected full cost for list views (avoids per-row recompute on cost_table)."""
    from projects.models import JobOrder, JobOrderCostSummary

    try:
        job_order = JobOrder.objects.select_related('cost_summary').get(job_no=job_no)
    except JobOrder.DoesNotExist:
        return

    estimated = build_job_cost_payload(job_order)['estimated']['total_cost']
    JobOrderCostSummary.objects.filter(job_order_id=job_no).update(
        estimated_total_cost=q2(Decimal(str(estimated))),
    )


def ensure_estimated_totals_cached(jobs) -> None:
    """Populate missing estimated_total_cost rows before cost_table serialization."""
    from projects.models import JobOrderCostSummary

    for job in jobs:
        try:
            summary = job.cost_summary
        except JobOrderCostSummary.DoesNotExist:
            _store_estimated_total_cost(job.job_no)
            continue
        if summary.estimated_total_cost is None:
            _store_estimated_total_cost(job.job_no)
            summary.refresh_from_db(fields=['estimated_total_cost'])


@transaction.atomic
def recompute_job_cost_summary(job_no: str) -> None:
    """
    Recompute and persist JobOrderCostSummary for the given job_no.

    Cost components (all in EUR):
      labor_cost          = WeldingJobCostAgg.total_cost + sum(PartCostAgg.total_cost)
      material_cost       = sum(JobOrderProcurementLine.amount_eur)
      subcontractor_cost  = non-paint SubcontractingAssignment costs + approved statement adjustments (job-linked) converted to EUR
      paint_cost          = paint SubcontractingAssignment costs (approved statement lines
                            use statement.approved_at date for FX; unbilled portion uses today)
      qc_cost             = sum(JobOrderQCCostLine.amount_eur)
      shipping_cost       = sum(JobOrderShippingCostLine.amount_eur)
      paint_material_cost = 4.00 TRY × total_weight_kg → EUR (only if painting task not skipped)
      general_expenses_cost = general_expenses_rate (TRY/kg) × total_weight_kg → EUR
      employee_overhead_cost = employee_overhead_rate × own labor_cost
      actual_total_cost   = sum of all above
    """
    from welding.models import WeldingJobCostAgg
    from tasks.models import PartCostAgg
    from subcontracting.models import SubcontractingAssignment, SubcontractorStatementLine, SubcontractorStatementAdjustment
    from projects.models import (
        JobOrder, JobOrderCostSummary,
        JobOrderProcurementLine, JobOrderQCCostLine, JobOrderShippingCostLine,
        JobOrderDepartmentTask,
    )

    today = date.today()

    # ------------------------------------------------------------------
    # 0. Fetch job order fields needed for new cost components
    # ------------------------------------------------------------------
    job_fields = (
        JobOrder.objects
        .values('total_weight_kg', 'general_expenses_rate')
        .filter(job_no=job_no)
        .first()
    )
    if job_fields is None:
        return
    total_weight_kg = Decimal(str(job_fields['total_weight_kg'] or 0))
    general_expenses_rate = Decimal(str(job_fields['general_expenses_rate'] or 0))

    # ------------------------------------------------------------------
    # 1. Labor = welding + machining (both already stored in EUR)
    # ------------------------------------------------------------------
    welding = (
        WeldingJobCostAgg.objects
        .filter(job_no=job_no)
        .values_list('total_cost', flat=True)
        .first()
    ) or Decimal('0')

    machining = (
        PartCostAgg.objects
        .filter(job_no_cached=job_no)
        .aggregate(s=Sum('total_cost'))['s']
    ) or Decimal('0')

    own_labor = q2(Decimal(welding) + Decimal(machining))
    labor = own_labor

    # ------------------------------------------------------------------
    # 2. Material = sum of saved procurement lines (unit_price is EUR)
    # ------------------------------------------------------------------
    material = q2(
        JobOrderProcurementLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    # ------------------------------------------------------------------
    # 3. Subcontractor = non-paint assignments with price_tier + weight
    # ------------------------------------------------------------------
    sc_assignments = (
        SubcontractingAssignment.objects
        .filter(
            department_task__job_order_id=job_no,
            price_tier__isnull=False,
            allocated_weight_kg__gt=0,
            is_retired=False,
        )
        .exclude(price_tier__tier_type='paint')
        .select_related('price_tier', 'department_task')
    )
    subcontractor = q2(sum(
        convert_to_eur(a.current_cost, a.cost_currency, today)
        for a in sc_assignments
    ))

    # Add approved statement adjustments linked to this job order
    sc_adjustments = (
        SubcontractorStatementAdjustment.objects
        .filter(
            job_order_id=job_no,
            statement__status='approved',
        )
        .select_related('statement')
    )
    for adj in sc_adjustments:
        subcontractor += convert_to_eur(adj.amount, adj.statement.currency, adj.statement.approved_at.date())
    subcontractor = q2(subcontractor)

    # ------------------------------------------------------------------
    # 4. Paint = paint assignments
    #    Billed portion: approved statement lines → use statement.approved_at for FX
    #    Unbilled portion: use today's rate
    # ------------------------------------------------------------------
    paint_statement_lines = (
        SubcontractorStatementLine.objects
        .filter(
            assignment__department_task__job_order_id=job_no,
            assignment__price_tier__tier_type='paint',
            statement__status='approved',
        )
        .select_related('statement', 'assignment')
    )
    paint_billed = sum(
        convert_to_eur(
            line.cost_amount,
            line.assignment.cost_currency,
            line.statement.approved_at.date(),
        )
        for line in paint_statement_lines
        if line.statement.approved_at
    )

    paint_assignments = (
        SubcontractingAssignment.objects
        .filter(
            department_task__job_order_id=job_no,
            price_tier__tier_type='paint',
            allocated_weight_kg__gt=0,
            is_retired=False,
        )
        .select_related('price_tier', 'department_task')
    )
    paint_unbilled = sum(
        convert_to_eur(a.unbilled_cost, a.cost_currency, today)
        for a in paint_assignments
    )

    paint = q2(Decimal(paint_billed) + Decimal(paint_unbilled))

    # ------------------------------------------------------------------
    # 5. QC and Shipping (amount_eur already stored by user)
    # ------------------------------------------------------------------
    qc = q2(
        JobOrderQCCostLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    shipping = q2(
        JobOrderShippingCostLine.objects
        .filter(job_order_id=job_no)
        .aggregate(s=Sum('amount_eur'))['s']
        or Decimal('0')
    )

    # ------------------------------------------------------------------
    # 6. Paint material cost = paint_material_rate (TRY/kg) × total_weight_kg → EUR
    #    Only if job has at least one non-skipped painting task
    #    Preserve user-customized rate; fall back to default 4.00
    # ------------------------------------------------------------------
    existing = JobOrderCostSummary.objects.filter(job_order_id=job_no).values(
        'paint_material_rate', 'employee_overhead_rate'
    ).first()

    paint_material_rate = (
        Decimal(str(existing['paint_material_rate']))
        if existing else Decimal('4.00')
    )

    painting_task = (
        JobOrderDepartmentTask.objects
        .filter(job_order_id=job_no, task_type='painting')
        .exclude(status='skipped')
        .values('manual_progress')
        .first()
    )
    painting_progress = Decimal(str(painting_task['manual_progress'] or 0)) if painting_task else Decimal('0')
    paint_material = q2(
        convert_to_eur(paint_material_rate * total_weight_kg * (painting_progress / Decimal('100')), 'TRY', today)
        if (total_weight_kg > 0 and painting_progress > 0) else Decimal('0')
    )

    # ------------------------------------------------------------------
    # 7. General expenses = general_expenses_rate (EUR/kg) × total_weight_kg
    # ------------------------------------------------------------------
    general_expenses = q2(
        general_expenses_rate * total_weight_kg
        if (general_expenses_rate > 0 and total_weight_kg > 0) else Decimal('0')
    )

    # ------------------------------------------------------------------
    # 8. Employee overhead = employee_overhead_rate × own labor_cost
    #    Preserve user-customized rate; fall back to default 0.65
    # ------------------------------------------------------------------
    employee_overhead_rate = (
        Decimal(str(existing['employee_overhead_rate']))
        if existing else Decimal('0.65')
    )
    employee_overhead = q2(employee_overhead_rate * own_labor)

    # ------------------------------------------------------------------
    # 9. Add direct children's rolled-up costs
    #    Each child's summary already includes its own descendants, so
    #    summing direct children avoids double-counting.
    # ------------------------------------------------------------------
    children_summaries = list(
        JobOrderCostSummary.objects.filter(job_order__parent_id=job_no)
    )
    if children_summaries:
        labor             += sum(s.labor_cost             for s in children_summaries)
        material          += sum(s.material_cost          for s in children_summaries)
        subcontractor     += sum(s.subcontractor_cost     for s in children_summaries)
        paint             += sum(s.paint_cost             for s in children_summaries)
        qc                += sum(s.qc_cost               for s in children_summaries)
        shipping          += sum(s.shipping_cost          for s in children_summaries)
        paint_material    += sum(s.paint_material_cost    for s in children_summaries)
        general_expenses  += sum(s.general_expenses_cost  for s in children_summaries)
        employee_overhead += sum(s.employee_overhead_cost for s in children_summaries)

    # ------------------------------------------------------------------
    # 10. Total and upsert
    # ------------------------------------------------------------------
    total = q2(
        labor + material + subcontractor + paint + qc + shipping
        + paint_material + general_expenses + employee_overhead
    )

    JobOrderCostSummary.objects.update_or_create(
        job_order_id=job_no,
        defaults={
            'labor_cost': q2(labor),
            'material_cost': q2(material),
            'subcontractor_cost': q2(subcontractor),
            'paint_cost': q2(paint),
            'qc_cost': q2(qc),
            'shipping_cost': q2(shipping),
            'paint_material_cost': q2(paint_material),
            'general_expenses_cost': q2(general_expenses),
            'employee_overhead_cost': q2(employee_overhead),
            'actual_total_cost': total,
        },
    )

    _store_estimated_total_cost(job_no)

    # ------------------------------------------------------------------
    # 11. Chain up: if this job has a parent, recompute the parent too
    # ------------------------------------------------------------------
    parent_id = (
        JobOrder.objects
        .values_list('parent_id', flat=True)
        .get(job_no=job_no)
    )
    if parent_id:
        recompute_job_cost_summary(parent_id)
