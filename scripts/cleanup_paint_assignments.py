"""
One-time cleanup: remove paint subcontracting assignments and their price tiers.

The painting department tasks themselves are NOT deleted — they are real department
tasks. Only the SubcontractingAssignment and SubcontractingPriceTier records are removed.

Statement lines that referenced these assignments are preserved — the FK is now
nullable (SET_NULL), so historical statement data is untouched.

Run via:
    python manage.py shell < scripts/cleanup_paint_assignments.py
"""

from django.db import transaction
from subcontracting.models import SubcontractingAssignment, SubcontractingPriceTier

with transaction.atomic():
    # Find all assignments where the linked task is itself a painting task
    # (old scheme: task_type='painting' on the subtask, not 'subcontracting')
    assignments = SubcontractingAssignment.objects.filter(
        department_task__task_type='painting',
    ).select_related('department_task__parent', 'price_tier')

    subtask_ids = list(assignments.values_list('department_task_id', flat=True))
    print(f"Paint assignments found: {assignments.count()}")
    for a in assignments:
        t = a.department_task
        print(f"  Assignment #{a.pk} | Subtask #{t.pk} '{t.title}' (job {t.job_order_id}) | Tier #{a.price_tier_id}")
    assignment_ids = list(assignments.values_list('pk', flat=True))
    tier_ids = list(assignments.values_list('price_tier_id', flat=True))
    print(f"\nAssignments to delete: {len(assignment_ids)} -> {assignment_ids}")
    print(f"Price tiers to delete: {tier_ids}")

    # Check statement lines — they should now have assignment set to NULL after migration
    from subcontracting.models import SubcontractorStatementLine
    lines_with_assignment = SubcontractorStatementLine.objects.filter(assignment_id__in=assignment_ids)
    print(f"\nStatement lines referencing these assignments: {lines_with_assignment.count()}")
    print("  (These will have assignment set to NULL — all snapshot data is preserved)")

    confirm = input("\nProceed with deletion? [yes/no]: ").strip().lower()
    if confirm != 'yes':
        print("Aborted.")
        raise SystemExit(0)

    # Delete assignments (statement lines become assignment=NULL via SET_NULL)
    deleted_a, _ = assignments.delete()
    print(f"Deleted {deleted_a} assignments.")

    # Delete price tiers (now unreferenced)
    deleted_t, _ = SubcontractingPriceTier.objects.filter(pk__in=tier_ids).delete()
    print(f"Deleted {deleted_t} price tiers.")

    print("\nDone. Painting department tasks are preserved. Run recompute_subcontractor_cost for affected job orders if needed.")
