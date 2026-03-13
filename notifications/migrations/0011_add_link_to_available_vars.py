"""
Add 'link' to available_vars for all notification types that were missing it.
"""
from django.db import migrations

TYPES_MISSING_LINK = [
    'sales_approval_requested',
    'sales_approved',
    'sales_rejected',
    'sales_converted',
    'sales_consultation',
    'qc_review_submitted',
    'qc_review_approved',
    'qc_review_rejected',
    'ncr_created',
    'ncr_submitted',
    'ncr_approved',
    'ncr_rejected',
    'ncr_assigned',
    'sub_approval_requested',
    'sub_approved',
    'sub_rejected',
    'password_reset',
]


def add_link(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in NotificationConfig.objects.filter(notification_type__in=TYPES_MISSING_LINK):
        updated = list(cfg.available_vars or [])
        if 'link' not in updated:
            updated.append('link')
        if cfg.notification_type == 'sales_consultation' and 'task_id' not in updated:
            # Insert task_id before task_title
            idx = updated.index('task_title') if 'task_title' in updated else len(updated)
            updated.insert(idx, 'task_id')
        if updated != list(cfg.available_vars or []):
            cfg.available_vars = updated
            cfg.save(update_fields=['available_vars'])


def remove_link(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in NotificationConfig.objects.filter(notification_type__in=TYPES_MISSING_LINK):
        updated = [v for v in (cfg.available_vars or []) if v != 'link']
        if cfg.notification_type == 'sales_consultation':
            updated = [v for v in updated if v != 'task_id']
        cfg.available_vars = updated
        cfg.save(update_fields=['available_vars'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0010_add_category_and_fix_source_id'),
    ]

    operations = [
        migrations.RunPython(add_link, reverse_code=remove_link),
    ]
