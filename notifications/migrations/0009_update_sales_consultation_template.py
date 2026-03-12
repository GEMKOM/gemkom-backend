"""
Update SALES_CONSULTATION NotificationConfig to include per-task context variables
(department, task_title, notes) so each consultation task gets its own notification body.
"""
from django.db import migrations


def patch_consultation(apps, schema_editor):
    from notifications.service import NOTIFICATION_CONFIG_DEFAULTS
    from notifications.models import Notification
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')

    d = NOTIFICATION_CONFIG_DEFAULTS.get(Notification.SALES_CONSULTATION)
    if not d:
        return

    NotificationConfig.objects.filter(
        notification_type=Notification.SALES_CONSULTATION
    ).update(
        title_template=d['title'],
        body_template=d['body'],
        available_vars=d['vars'],
    )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0008_notificationconfig_delivery_defaults'),
    ]

    operations = [
        migrations.RunPython(patch_consultation, migrations.RunPython.noop),
    ]
