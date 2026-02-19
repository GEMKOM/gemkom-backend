# -*- coding: utf-8 -*-
"""
Migration script: Replace Montaj + Kaynak + Temizlik subtasks under each
manufacturing main task with a single 'Kaynaklı İmalat' subtask.

Run with:
    python manage.py shell -c "exec(open('scripts/migrate_kaynak_subtasks.py', encoding='utf-8').read())"
"""

import django
import os

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()

from decimal import Decimal, ROUND_HALF_UP
from projects.models import JobOrder, JobOrderDepartmentTask

OLD_TITLES  = {'Montaj', 'Kaynak', 'Temizlik'}
NEW_TITLE   = 'Kaynaklı İmalat'
BAD_TITLE   = 'KaynaklÄ± Ä°malat'   # mojibake written by earlier runs

DRY_RUN = False

# ---------------------------------------------------------------------------
# Step 0: Repair any mojibake records created by earlier runs
# ---------------------------------------------------------------------------
bad_records = JobOrderDepartmentTask.objects.filter(title=BAD_TITLE)
bad_count = bad_records.count()
if bad_count:
    print(f"Repairing {bad_count} mojibake record(s)...")
    if not DRY_RUN:
        bad_records.update(title=NEW_TITLE)
    print(f"  {'[DRY RUN] ' if DRY_RUN else ''}Fixed {bad_count} record(s).\n")
else:
    print("No mojibake records found.\n")

# ---------------------------------------------------------------------------
# Step 1: Migrate remaining old subtasks
# ---------------------------------------------------------------------------
print(f"{'[DRY RUN] ' if DRY_RUN else ''}Starting migration...\n")

mfg_tasks = JobOrderDepartmentTask.objects.filter(
    parent__isnull=True,
    department='manufacturing',
    subtasks__title__in=OLD_TITLES,
).distinct()

created_count = 0
deleted_count = 0
skipped_count = 0
affected_job_nos = set()

for mfg_task in mfg_tasks:
    old_subtasks = list(mfg_task.subtasks.filter(title__in=OLD_TITLES))

    if not old_subtasks:
        skipped_count += 1
        continue

    total_weight  = sum(s.weight for s in old_subtasks)
    weighted_prog = sum(Decimal(s.weight) * s.manual_progress for s in old_subtasks)

    combined_progress = (weighted_prog / Decimal(total_weight)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    combined_progress = min(combined_progress, Decimal('100.00'))
    capped_weight = min(total_weight, 100)

    statuses = {s.status for s in old_subtasks}
    if statuses == {'completed'}:
        new_status = 'completed'
    elif 'in_progress' in statuses:
        new_status = 'in_progress'
    elif 'pending' in statuses:
        new_status = 'pending'
    else:
        new_status = sorted(old_subtasks, key=lambda s: s.id)[0].status

    first_sequence = min(s.sequence for s in old_subtasks)

    print(
        f"  [{mfg_task.job_order_id}] {mfg_task.title}\n"
        f"    Old: {[f'{s.title} w={s.weight} p={s.manual_progress}%' for s in old_subtasks]}\n"
        f"    New: title='{NEW_TITLE}' weight={capped_weight} "
        f"progress={combined_progress}% status={new_status}"
        + (f" (weight capped from {total_weight})" if capped_weight < total_weight else "")
    )

    if not DRY_RUN:
        JobOrderDepartmentTask.objects.create(
            job_order=mfg_task.job_order,
            department=mfg_task.department,
            parent=mfg_task,
            title=NEW_TITLE,
            status=new_status,
            weight=capped_weight,
            manual_progress=combined_progress,
            sequence=first_sequence,
        )
        for s in old_subtasks:
            s.delete()

    created_count += 1
    deleted_count += len(old_subtasks)
    affected_job_nos.add(mfg_task.job_order_id)

print(f"\n{'[DRY RUN] ' if DRY_RUN else ''}Summary:")
print(f"  Created : {created_count}")
print(f"  Deleted : {deleted_count}")
print(f"  Skipped : {skipped_count}")

# ---------------------------------------------------------------------------
# Step 2: Recalculate completion percentages
# ---------------------------------------------------------------------------
all_affected = affected_job_nos | set(
    JobOrderDepartmentTask.objects.filter(title=NEW_TITLE)
    .values_list('job_order_id', flat=True)
)

if not DRY_RUN and all_affected:
    print(f"\nRecalculating completion for {len(all_affected)} job orders...")
    for job in JobOrder.objects.filter(job_no__in=all_affected):
        job.update_completion_percentage()
        print(f"  {job.job_no}: {job.completion_percentage}%")
    print("Done.")
