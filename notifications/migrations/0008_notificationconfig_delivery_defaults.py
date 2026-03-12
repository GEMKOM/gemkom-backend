from django.db import migrations, models


def populate_delivery_defaults(apps, schema_editor):
    from notifications.service import NOTIFICATION_DEFAULTS
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')

    to_update = []
    for cfg in NotificationConfig.objects.all():
        send_email, send_in_app = NOTIFICATION_DEFAULTS.get(cfg.notification_type, (True, True))
        cfg.default_send_email  = send_email
        cfg.default_send_in_app = send_in_app
        to_update.append(cfg)

    if to_update:
        NotificationConfig.objects.bulk_update(to_update, ['default_send_email', 'default_send_in_app'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0007_update_config_link_in_body'),
    ]

    operations = [
        migrations.AddField(
            model_name='notificationconfig',
            name='default_send_email',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='notificationconfig',
            name='default_send_in_app',
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(populate_delivery_defaults, migrations.RunPython.noop),
    ]
