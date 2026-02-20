"""
Auto-assignment service for paint (boya) subcontractor.

All paint jobs are handled by a fixed subcontractor. When a task with
task_type='painting' is saved, this service automatically creates:
  1. A "Boya" SubcontractingPriceTier for the job order (price=0 initially)
  2. A SubcontractingAssignment linking the task to the paint subcontractor
  3. Sets allocated_weight_kg = sum of all other (non-paint) tiers

The price_per_kg starts at 0 and is updated later by manufacturing.
"""

from decimal import Decimal

from django.db.models import Sum

PAINT_SUBCONTRACTOR_ID = 9
PAINT_TIER_NAME = 'Boya'


def ensure_paint_assignment(task) -> None:
    """
    Idempotent. Called when a task with task_type='painting' is saved.
    Creates the paint price tier and assignment if they don't exist, then syncs weight.
    """
    from subcontracting.models import (
        Subcontractor, SubcontractingAssignment, SubcontractingPriceTier
    )

    job_order = task.job_order

    # Get or create the paint tier for this job order (one per job)
    paint_tier, _ = SubcontractingPriceTier.objects.get_or_create(
        job_order=job_order,
        name=PAINT_TIER_NAME,
        defaults={
            'price_per_kg': Decimal('0'),
            'allocated_weight_kg': Decimal('0.01'),  # placeholder, synced below
        }
    )

    # Get or create the assignment
    subcontractor = Subcontractor.objects.get(id=PAINT_SUBCONTRACTOR_ID)
    SubcontractingAssignment.objects.get_or_create(
        department_task=task,
        defaults={
            'subcontractor': subcontractor,
            'price_tier': paint_tier,
            'allocated_weight_kg': Decimal('0.01'),  # placeholder, synced below
        }
    )

    # Now sync the weight
    sync_paint_assignment_weight(job_order)


def sync_paint_assignment_weight(job_order) -> None:
    """
    Update paint tier + all painting assignments for this job order.
    allocated_weight_kg = sum of all non-paint SubcontractingPriceTiers for this job.
    Called when tiers are added, changed, or deleted.
    """
    from subcontracting.models import SubcontractingAssignment, SubcontractingPriceTier

    total = SubcontractingPriceTier.objects.filter(
        job_order=job_order
    ).exclude(name=PAINT_TIER_NAME).aggregate(
        total=Sum('allocated_weight_kg')
    )['total'] or Decimal('0')

    # Enforce model minimum constraint
    weight = max(total, Decimal('0.01'))

    SubcontractingPriceTier.objects.filter(
        job_order=job_order,
        name=PAINT_TIER_NAME,
    ).update(allocated_weight_kg=weight)

    SubcontractingAssignment.objects.filter(
        department_task__job_order=job_order,
        department_task__task_type='painting',
    ).update(allocated_weight_kg=weight)
