from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from subcontracting.models import (
    SubcontractingAssignment,
    SubcontractorStatement,
    SubcontractorStatementLine,
)


@transaction.atomic
def generate_or_refresh_statement(
    subcontractor_id: int,
    year: int,
    month: int,
    created_by=None,
) -> SubcontractorStatement:
    """
    Create or refresh a monthly statement for a subcontractor.

    Only DRAFT and REJECTED statements can be refreshed.
    Line items represent the DELTA progress since the last approved statement
    (i.e. assignment.last_billed_progress → current manual_progress).

    Assignments with zero delta progress are skipped.
    Existing adjustments are preserved when refreshing.
    """
    statement, _ = SubcontractorStatement.objects.get_or_create(
        subcontractor_id=subcontractor_id,
        year=year,
        month=month,
        defaults={
            'status': 'draft',
            'currency': 'TRY',
            'created_by': created_by,
        },
    )

    if statement.status not in ('draft', 'rejected'):
        raise ValueError(
            f"Yalnızca 'taslak' veya 'reddedildi' durumundaki hakedişler yenilenebilir. "
            f"Mevcut durum: {statement.get_status_display()}"
        )

    # Wipe existing line items — we will re-snapshot from current data.
    # Adjustments are intentionally kept.
    statement.line_items.all().delete()

    # All assignments for this subcontractor that have any unbilled progress.
    assignments = (
        SubcontractingAssignment.objects
        .filter(subcontractor_id=subcontractor_id)
        .select_related('department_task__job_order', 'price_tier')
    )

    lines = []
    for assignment in assignments:
        current_prog = assignment.department_task.manual_progress or Decimal('0')
        previous_prog = assignment.last_billed_progress
        delta = current_prog - previous_prog

        if delta <= Decimal('0'):
            # Nothing new to bill for this assignment
            continue

        effective_weight = (assignment.allocated_weight_kg * delta / Decimal('100')).quantize(Decimal('0.0001'))
        cost = (effective_weight * assignment.price_tier.price_per_kg).quantize(Decimal('0.01'))

        lines.append(SubcontractorStatementLine(
            statement=statement,
            assignment=assignment,
            job_no=assignment.department_task.job_order_id,
            job_title=getattr(assignment.department_task.job_order, 'title', ''),
            subcontractor_name=assignment.subcontractor.name,
            price_tier_name=assignment.price_tier.name,
            allocated_weight_kg=assignment.allocated_weight_kg,
            previous_progress=previous_prog,
            current_progress=current_prog,
            delta_progress=delta,
            effective_weight_kg=effective_weight,
            price_per_kg=assignment.price_tier.price_per_kg,
            cost_amount=cost,
        ))

    SubcontractorStatementLine.objects.bulk_create(lines)

    statement.recalculate_totals()
    statement.save(update_fields=['work_total', 'adjustment_total', 'grand_total', 'updated_at'])

    return statement


@transaction.atomic
def advance_billed_progress(statement: SubcontractorStatement) -> None:
    """
    Called after a statement is approved.
    Advances last_billed_progress on each assignment to the current_progress
    snapshot stored in the statement lines, locking in the "paid up to" baseline.
    """
    lines = statement.line_items.select_related('assignment').all()
    for line in lines:
        assignment = line.assignment
        # Only advance — never go backwards (progress can't decrease, but be safe)
        if line.current_progress > assignment.last_billed_progress:
            assignment.last_billed_progress = line.current_progress
            assignment.save(update_fields=['last_billed_progress'])

    statement.approved_at = timezone.now()
    statement.save(update_fields=['approved_at'])
