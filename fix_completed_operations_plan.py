"""
One-time script to clear planning fields for completed operations.

This fixes the issue where completed operations were not being removed from the plan,
causing unique constraint violations when trying to assign their plan_order to other operations.

Usage:
    python manage.py shell < fix_completed_operations_plan.py

Or run in Django shell:
    from tasks.models import Operation
    exec(open('fix_completed_operations_plan.py').read())
"""

from tasks.models import Operation

# Find all completed operations that still have planning fields set
completed_with_plan = Operation.objects.filter(
    completion_date__isnull=False,
    plan_order__isnull=False
)

count = completed_with_plan.count()
print(f"Found {count} completed operations still in plan")

if count > 0:
    # Clear planning fields for these operations
    updated = completed_with_plan.update(
        in_plan=False,
        plan_order=None,
        planned_start_ms=None,
        planned_end_ms=None,
        plan_locked=False
    )
    print(f"Successfully cleared planning fields for {updated} operations")
else:
    print("No operations to fix")
