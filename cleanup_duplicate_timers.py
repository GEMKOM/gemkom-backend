"""
Script to cleanup duplicate active timers by keeping only the earliest one.
This should be run BEFORE applying the unique constraint migration.

Run with: python cleanup_duplicate_timers.py
(Make sure to activate your virtual environment first)
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from tasks.models import Timer
from django.db.models import Count
import time

# Find duplicate active timers
duplicates = Timer.objects.filter(
    finish_time__isnull=True
).values(
    'user', 'machine_fk', 'content_type', 'object_id'
).annotate(
    count=Count('id')
).filter(count__gt=1)

print(f"\n{'='*60}")
print(f"DUPLICATE ACTIVE TIMERS CLEANUP")
print(f"{'='*60}\n")

if not duplicates:
    print("✅ No duplicate active timers found!")
    print("Nothing to cleanup.\n")
    exit(0)

print(f"Found {len(duplicates)} groups with duplicate active timers.\n")

total_stopped = 0

for dup in duplicates:
    user_id = dup['user']
    machine_id = dup['machine_fk']
    content_type_id = dup['content_type']
    object_id = dup['object_id']
    count = dup['count']

    # Get the actual timer objects, ordered by start_time (earliest first)
    timers = Timer.objects.filter(
        user_id=user_id,
        machine_fk_id=machine_id,
        content_type_id=content_type_id,
        object_id=object_id,
        finish_time__isnull=True
    ).select_related('user', 'machine_fk').order_by('start_time')

    # Keep the earliest timer, stop the rest
    earliest_timer = timers[0]
    duplicate_timers = timers[1:]

    print(f"Group: User={earliest_timer.user.username}, Machine={earliest_timer.machine_fk.name if earliest_timer.machine_fk else 'None'}, Task={object_id}")
    print(f"  ✅ Keeping timer ID={earliest_timer.id} (started at {earliest_timer.start_time})")

    current_time_ms = int(time.time() * 1000)

    for timer in duplicate_timers:
        print(f"  ❌ Stopping duplicate timer ID={timer.id} (started at {timer.start_time})")
        timer.finish_time = current_time_ms
        timer.save()
        total_stopped += 1

    print()

print(f"{'='*60}")
print(f"✅ Cleanup complete!")
print(f"   - Stopped {total_stopped} duplicate timer(s)")
print(f"   - Kept {len(duplicates)} timer(s) (earliest in each group)")
print(f"\nYou can now safely apply the migration.")
print(f"{'='*60}\n")
