"""
Script to check for duplicate active timers before applying the unique constraint.
Run this with: python manage.py shell < check_duplicate_timers.py
Or activate your virtual environment and run: python check_duplicate_timers.py
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from tasks.models import Timer
from django.db.models import Count

# Find duplicate active timers
duplicates = Timer.objects.filter(
    finish_time__isnull=True
).values(
    'user', 'machine_fk', 'content_type', 'object_id'
).annotate(
    count=Count('id')
).filter(count__gt=1)

print(f"\n{'='*60}")
print(f"DUPLICATE ACTIVE TIMERS CHECK")
print(f"{'='*60}\n")

if duplicates:
    print(f"⚠️  Found {len(duplicates)} groups with duplicate active timers:\n")

    for dup in duplicates:
        user_id = dup['user']
        machine_id = dup['machine_fk']
        content_type_id = dup['content_type']
        object_id = dup['object_id']
        count = dup['count']

        # Get the actual timer objects
        timers = Timer.objects.filter(
            user_id=user_id,
            machine_fk_id=machine_id,
            content_type_id=content_type_id,
            object_id=object_id,
            finish_time__isnull=True
        ).select_related('user', 'machine_fk')

        print(f"  Group: User={timers[0].user.username}, Machine={timers[0].machine_fk.name if timers[0].machine_fk else 'None'}, Task={object_id}")
        print(f"  Count: {count} active timers")
        print(f"  Timer IDs: {[t.id for t in timers]}")
        print(f"  Start times: {[t.start_time for t in timers]}")
        print()

    print("\n⚠️  ACTION REQUIRED:")
    print("You need to resolve these duplicates before applying the migration.")
    print("Options:")
    print("1. Stop the duplicate timers manually")
    print("2. Keep only the earliest timer and stop the rest")
    print("3. Contact users to resolve their timers\n")
else:
    print("✅ No duplicate active timers found!")
    print("The migration can be applied safely.\n")

print(f"{'='*60}\n")
