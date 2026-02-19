# -*- coding: utf-8 -*-
"""
Data migration: populate task_type on existing JobOrderDepartmentTask rows
from their title strings.

Run with:
    python manage.py shell -c "exec(open('scripts/populate_task_type.py', encoding='utf-8').read())"
"""

from projects.models import JobOrderDepartmentTask

TITLE_TO_TYPE = {
    'CNC Kesim': 'cnc_cutting',
    'Talaşlı İmalat': 'machining',
    'Kaynaklı İmalat': 'welding',
}

total_updated = 0

for title, task_type in TITLE_TO_TYPE.items():
    count = JobOrderDepartmentTask.objects.filter(
        title=title, task_type__isnull=True
    ).update(task_type=task_type)
    print(f"  '{title}' -> '{task_type}': {count} record(s) updated.")
    total_updated += count

print(f"\nDone. Total updated: {total_updated}")
