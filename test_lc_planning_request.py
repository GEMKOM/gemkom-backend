"""
Dry-run test: simulate the planning request items that would be created
for a given LinearCuttingSession, without writing anything to the database.

Usage:
    python test_lc_planning_request.py
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from collections import defaultdict
from decimal import Decimal
from django.db.models import Q

from linear_cutting.models import LinearCuttingSession

SESSION_KEY = 'LC-0007'

# ─── Load session ─────────────────────────────────────────────────────────────
try:
    session = LinearCuttingSession.objects.prefetch_related(
        'parts', 'parts__item'
    ).get(key=SESSION_KEY)
except LinearCuttingSession.DoesNotExist:
    print(f"Session {SESSION_KEY} not found.")
    raise SystemExit(1)

print(f"Session : {session.key} — {session.title}")
print(f"Default stock length : {session.stock_length_mm} mm")
print(f"Kerf : {session.kerf_mm} mm")
print()

groups = (session.optimization_result or {}).get('groups', [])
if not groups:
    print("No optimization result found.")
    raise SystemExit(1)

# ─── Simulate planning request items ──────────────────────────────────────────
print(f"{'='*70}")
print(f"Simulated PlanningRequestItems for {SESSION_KEY}")
print(f"{'='*70}\n")

order_idx = 1
total_quantity = Decimal('0')

for group in groups:
    item_id   = group['item_id']
    item_name = group.get('item_name', '?')
    item_code = group.get('item_code', '?')
    stock_len = group['stock_length_mm']
    stock_len_m = stock_len // 1000

    # Fetch item unit
    from procurement.models import Item as ProcurementItem
    item_obj = ProcurementItem.objects.get(pk=item_id)
    item_unit = (item_obj.unit or '').lower()

    # Parts for this group
    from linear_cutting.models import LinearCuttingPart
    group_parts_qs = LinearCuttingPart.objects.filter(session=session, item_id=item_id)
    if stock_len == session.stock_length_mm:
        group_parts_qs = group_parts_qs.filter(
            Q(stock_length_mm=stock_len) | Q(stock_length_mm__isnull=True)
        )
    else:
        group_parts_qs = group_parts_qs.filter(stock_length_mm=stock_len)

    distinct_job_nos = list(
        group_parts_qs.order_by('job_no').values_list('job_no', flat=True).distinct()
    )

    # Assign each bar to the job_no with the most cut length on it
    bars_by_job_no = defaultdict(int)
    for bar in group['bars']:
        cut_mm_by_job = defaultdict(float)
        for cut in bar['cuts']:
            cut_mm_by_job[cut['job_no']] += cut['effective_mm']
        dominant_job = max(cut_mm_by_job, key=lambda j: cut_mm_by_job[j])
        bars_by_job_no[dominant_job] += 1

    print(f"Item     : {item_name} ({item_code})")
    print(f"Unit     : {item_unit}  |  Stock length: {stock_len} mm  |  Bars needed: {group['bars_needed']}")
    print(f"Efficiency: {group['efficiency_pct']}%  |  Total waste: {group['total_waste_mm']} mm")
    print()

    for job_no in distinct_job_nos:
        parts_for_job = list(group_parts_qs.filter(job_no=job_no))
        bars_for_job = bars_by_job_no.get(job_no, 0)

        if item_unit == 'metre':
            quantity = Decimal(str(bars_for_job * (stock_len / 1000)))
        else:
            quantity = Decimal(bars_for_job)

        item_description = f"{bars_for_job} boy {stock_len_m} metre"
        specs = ", ".join(
            f"{p.label} {p.nominal_length_mm}mm ×{p.quantity}"
            for p in parts_for_job
        )
        total_cut_mm = sum(p.nominal_length_mm * p.quantity for p in parts_for_job)

        total_quantity += quantity

        print(f"  [{order_idx}] Job No        : {job_no or '(none)'}")
        print(f"      Quantity       : {quantity} {item_unit}  (cuts: {total_cut_mm/1000:.3f} m)")
        print(f"      Description    : \"{item_description}\"")
        print(f"      Specs          : {specs}")
        print()
        order_idx += 1

print(f"{'='*70}")
print(f"Total line items : {order_idx - 1}")
print(f"Grand total qty  : {total_quantity} {item_unit}")
print(f"{'='*70}")
