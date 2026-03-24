from django.db import migrations


def add_task_assigned_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.get_or_create(
        notification_type='task_assigned',
        defaults={
            'title_template': 'Göreve Atandınız: {task_title}',
            'body_template': '{actor} sizi "{task_title}" görevine atadı.',
            'link_template': '',
            'available_vars': ['actor', 'task_title', 'task_id', 'offer_no', 'department'],
            'default_send_email': True,
            'default_send_in_app': True,
        },
    )


def remove_task_assigned_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(notification_type='task_assigned').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0015_migrate_teams_to_groups'),
    ]

    operations = [
        migrations.RunPython(add_task_assigned_config, reverse_code=remove_task_assigned_config),
    ]
