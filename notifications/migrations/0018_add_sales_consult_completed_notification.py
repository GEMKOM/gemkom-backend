from django.db import migrations


def add_sales_consult_completed_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.get_or_create(
        notification_type='sales_consult_completed',
        defaults={
            'title_template': '[Danışma Tamamlandı] {offer_no} – {task_title}',
            'body_template': (
                '{offer_no} numaralı "{offer_title}" teklifi için "{task_title}" danışma görevi tamamlandı.\n'
                'Müşteri: {customer}\n'
                'Departman: {department}\n'
                'Tamamlayan: {completed_by}'
            ),
            'link_template': '',
            'available_vars': ['offer_no', 'offer_title', 'customer', 'department', 'task_title', 'completed_by', 'link'],
            'default_send_email': True,
            'default_send_in_app': True,
        },
    )


def remove_sales_consult_completed_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(notification_type='sales_consult_completed').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0017_add_department_to_task_assigned_vars'),
    ]

    operations = [
        migrations.RunPython(
            add_sales_consult_completed_config,
            reverse_code=remove_sales_consult_completed_config,
        ),
    ]
