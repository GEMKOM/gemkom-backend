"""
Add 'department_code' to available_vars for sales_consultation notification type.
"""
from django.db import migrations


def add_department_code(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='sales_consultation').first()
    if cfg and 'department_code' not in (cfg.available_vars or []):
        updated = list(cfg.available_vars or [])
        idx = updated.index('task_id') if 'task_id' in updated else len(updated)
        updated.insert(idx, 'department_code')
        cfg.available_vars = updated
        cfg.save(update_fields=['available_vars'])


def remove_department_code(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='sales_consultation').first()
    if cfg:
        cfg.available_vars = [v for v in (cfg.available_vars or []) if v != 'department_code']
        cfg.save(update_fields=['available_vars'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0012_add_task_id_to_sales_consultation_vars'),
    ]

    operations = [
        migrations.RunPython(add_department_code, reverse_code=remove_department_code),
    ]
