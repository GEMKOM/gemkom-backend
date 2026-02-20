# -*- coding: utf-8 -*-
"""
Data migration: set task_type='painting' on existing Boya tasks,
then trigger ensure_paint_assignment for each.

Run with:
    python manage.py shell -c "exec(open('scripts/populate_painting_tasks.py', encoding='utf-8').read())"
"""

from projects.models import JobOrderDepartmentTask
from subcontracting.services.painting import ensure_paint_assignment

# 1. Set task_type='painting' on all Boya tasks that don't have it yet
updated = JobOrderDepartmentTask.objects.filter(
    title='Boya',
    task_type__isnull=True
).update(task_type='painting')
print(f"Set task_type='painting' on {updated} tasks.")

# 2. Create paint assignments for all painting tasks
painting_tasks = JobOrderDepartmentTask.objects.filter(
    task_type='painting'
).select_related('job_order')

created = 0
skipped = 0
for task in painting_tasks:
    try:
        ensure_paint_assignment(task)
        created += 1
    except Exception as e:
        print(f"  ERROR on task {task.id} ({task.job_order_id}): {e}")
        skipped += 1

print(f"ensure_paint_assignment: {created} processed, {skipped} errors.")
print("Done.")
