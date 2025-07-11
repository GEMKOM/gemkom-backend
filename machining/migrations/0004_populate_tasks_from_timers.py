# Generated by Django 5.2.3 on 2025-07-03 12:56

from django.db import migrations

def copy_timers_to_tasks(apps, schema_editor):
    Timer = apps.get_model('machining', 'Timer')
    Task = apps.get_model('machining', 'Task')

    seen_keys = set()

    for timer in Timer.objects.all().order_by('start_time'):
        key = timer.issue_key

        # Skip if already created
        if key in seen_keys:
            continue

        seen_keys.add(key)

        Task.objects.update_or_create(
            key=key,
            defaults={
                'name': key,
                'job_no': timer.job_no,
                'image_no': timer.image_no,
                'position_no': timer.position_no,
                'quantity': timer.quantity,
            }
        )
class Migration(migrations.Migration):

    dependencies = [
        ('machining', '0003_task_alter_timer_issue_key'),
    ]

    operations = [
        migrations.RunPython(copy_timers_to_tasks),
    ]
