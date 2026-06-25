from django.db import migrations


NOTIFY_BODY = (
    '{customer} müşterisi için sipariş onaylandı.\n\n'
    'Sipariş Numarası: {order_no}\n'
    'İş Emri No: {job_no}\n'
    'İletişim Kişisi: {contact_person}\n'
    'Telefon: {phone}\n'
    'Adres: {address}\n'
    'Vergi Numarası: {tax_id}\n'
    'Vergi Dairesi: {tax_office}\n'
    'Teslim Şekli: {delivery_line}\n'
    'Teslim Süresi: {delivery_date}\n'
    'Sipariş Tutarı: {amount}\n'
    'Ödeme Şekli: {payment_terms}\n'
    'Teklif No: {offer_no}\n'
    'Teklifi Oluşturan: {offer_creator}\n'
    'İletişim E-posta: {offer_creator_email}\n\n'
    '{link}'
)

NOTIFY_VARS = [
    'customer', 'customer_id', 'offer_no', 'job_no', 'order_no', 'contact_person', 'phone', 'address',
    'tax_id', 'tax_office', 'delivery_line', 'delivery_date', 'amount',
    'payment_terms', 'offer_creator', 'offer_creator_email', 'link',
]


def update_notify_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(
        notification_type='sales_order_confirmed_notify',
    ).update(
        body_template=NOTIFY_BODY,
        available_vars=NOTIFY_VARS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0035_customer_edit_link_notify'),
    ]

    operations = [
        migrations.RunPython(update_notify_config, migrations.RunPython.noop),
    ]
