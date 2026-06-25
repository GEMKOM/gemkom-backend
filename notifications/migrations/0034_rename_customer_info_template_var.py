from django.db import migrations


def rename_customer_link_in_templates(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(
        notification_type='sales_order_confirmed_notify',
    ).first()
    if not cfg:
        return
    cfg.body_template = cfg.body_template.replace(
        'Müşteri Linki: {customer_link}',
        'Müşteri Bilgisi: {customer_info}',
    )
    cfg.link_template = cfg.link_template.replace('{customer_link}', '{customer_info}')
    if isinstance(cfg.available_vars, list):
        cfg.available_vars = [
            'customer_info' if v == 'customer_link' else v
            for v in cfg.available_vars
        ]
    cfg.save(update_fields=['body_template', 'link_template', 'available_vars'])


def reverse_rename(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    cfg = NotificationConfig.objects.filter(
        notification_type='sales_order_confirmed_notify',
    ).first()
    if not cfg:
        return
    cfg.body_template = cfg.body_template.replace(
        'Müşteri Bilgisi: {customer_info}',
        'Müşteri Linki: {customer_link}',
    )
    cfg.link_template = cfg.link_template.replace('{customer_info}', '{customer_link}')
    if isinstance(cfg.available_vars, list):
        cfg.available_vars = [
            'customer_link' if v == 'customer_info' else v
            for v in cfg.available_vars
        ]
    cfg.save(update_fields=['body_template', 'link_template', 'available_vars'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0033_add_sales_order_confirmed_notify'),
    ]

    operations = [
        migrations.RunPython(rename_customer_link_in_templates, reverse_rename),
    ]
