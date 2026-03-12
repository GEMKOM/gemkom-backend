"""
Patch existing NotificationConfig rows to include {link} in body templates
and add 'link' to available_vars for types that have a non-empty link template.
"""
from django.db import migrations


def patch_body_templates(apps, schema_editor):
    from notifications.service import NOTIFICATION_CONFIG_DEFAULTS
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')

    to_update = []
    for cfg in NotificationConfig.objects.all():
        defaults = NOTIFICATION_CONFIG_DEFAULTS.get(cfg.notification_type)
        if not defaults:
            continue
        new_body = defaults['body']
        new_vars = defaults['vars']
        if cfg.body_template != new_body or cfg.available_vars != new_vars:
            cfg.body_template = new_body
            cfg.available_vars = new_vars
            to_update.append(cfg)

    if to_update:
        NotificationConfig.objects.bulk_update(to_update, ['body_template', 'available_vars'])


def reverse_patch(apps, schema_editor):
    pass  # no meaningful reverse


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0006_remove_notification_route'),
    ]

    operations = [
        migrations.RunPython(patch_body_templates, reverse_patch),
    ]
