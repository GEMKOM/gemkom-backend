from django.db import migrations


def add_department_var(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='task_assigned').first()
    if cfg and 'department' not in (cfg.available_vars or []):
        cfg.available_vars = list(cfg.available_vars or []) + ['department']
        cfg.save(update_fields=['available_vars'])


def remove_department_var(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(notification_type='task_assigned').first()
    if cfg:
        cfg.available_vars = [v for v in (cfg.available_vars or []) if v != 'department']
        cfg.save(update_fields=['available_vars'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0016_add_task_assigned_notification'),
    ]

    operations = [
        migrations.RunPython(add_department_var, reverse_code=remove_department_var),
    ]
