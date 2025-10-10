# tasks/migrations/0002_migrate_machining_data.py
from django.db import migrations

def forwards_func(apps, schema_editor):
    """
    Copies data from the old machining.Timer and machining.TaskKeyCounter
    to the new generic tasks.Timer and tasks.TaskKeyCounter models.
    """
    # Get historical models to ensure this migration is always runnable
    OldTimer = apps.get_model('machining', 'Timer')
    OldTaskKeyCounter = apps.get_model('machining', 'TaskKeyCounter')
    MachiningTask = apps.get_model('machining', 'Task')

    NewTimer = apps.get_model('tasks', 'Timer')
    NewTaskKeyCounter = apps.get_model('tasks', 'TaskKeyCounter')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    # --- Migrate TaskKeyCounter data ---
    new_counters = []
    for old_counter in OldTaskKeyCounter.objects.all().iterator():
        new_counters.append(
            NewTaskKeyCounter(
                id=old_counter.id,
                prefix=old_counter.prefix,
                current=old_counter.current
            )
        )
    NewTaskKeyCounter.objects.bulk_create(new_counters, ignore_conflicts=True)

    # --- Migrate Timer data ---
    # Get the ContentType for the MachiningTask model, which all old timers point to
    task_content_type = ContentType.objects.get_for_model(MachiningTask)

    new_timers = []
    # Use iterator() for memory efficiency on large tables
    for old_timer in OldTimer.objects.all().iterator():
        new_timers.append(
            NewTimer(
                id=old_timer.id,  # Preserve original ID
                user_id=old_timer.user_id,
                stopped_by_id=old_timer.stopped_by_id,
                start_time=old_timer.start_time,
                finish_time=old_timer.finish_time,
                manual_entry=old_timer.manual_entry,
                comment=old_timer.comment,
                machine_fk_id=old_timer.machine_fk_id,
                # --- This is the crucial part for the Generic Foreign Key ---
                content_type=task_content_type,
                object_id=old_timer.issue_key_id,
            )
        )

    # Bulk create for high performance
    NewTimer.objects.bulk_create(new_timers, batch_size=500)

def reverse_func(apps, schema_editor):
    """
    Deletes the migrated data from the new models. This makes the migration reversible.
    """
    NewTimer = apps.get_model('tasks', 'Timer')
    NewTaskKeyCounter = apps.get_model('tasks', 'TaskKeyCounter')
    NewTimer.objects.all().delete()
    NewTaskKeyCounter.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0001_initial'),
        # This migration needs the old models to exist, so it depends on their
        # latest migration state in the 'machining' app.
        ('machining', '0020_remove_jobcostagg_agg_jobno_idx_and_more'), # Replace with your actual latest machining migration
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(forwards_func, reverse_code=reverse_func),
    ]
