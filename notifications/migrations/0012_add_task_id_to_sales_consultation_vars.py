"""
Add 'task_id' to available_vars for sales_consultation notification type.
"""
from django.db import migrations


def add_task_id(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='sales_consultation').first()
    if cfg and 'task_id' not in (cfg.available_vars or []):
        updated = list(cfg.available_vars or [])
        idx = updated.index('task_title') if 'task_title' in updated else len(updated)
        updated.insert(idx, 'task_id')
        cfg.available_vars = updated
        cfg.save(update_fields=['available_vars'])


def remove_task_id(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='sales_consultation').first()
    if cfg:
        cfg.available_vars = [v for v in (cfg.available_vars or []) if v != 'task_id']
        cfg.save(update_fields=['available_vars'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0011_add_link_to_available_vars'),
    ]

    operations = [
        migrations.RunPython(add_task_id, reverse_code=remove_task_id),
    ]
