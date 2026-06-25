from django.db import migrations, models


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
    'Ödeme Şekli: {payment_terms}\n\n'
    '{link}'
)

NOTIFY_VARS = [
    'customer', 'customer_id', 'job_no', 'order_no', 'contact_person', 'phone', 'address',
    'tax_id', 'tax_office', 'delivery_line', 'delivery_date', 'amount',
    'payment_terms', 'link',
]

CHOICES = [
    ('pr_approval_requested', 'Satınalma Onayı Bekleniyor'),
    ('pr_approved', 'Satınalma Talebi Onaylandı'),
    ('pr_rejected', 'Satınalma Talebi Reddedildi'),
    ('pr_po_created', 'Satınalma Siparişi Oluşturuldu'),
    ('ot_approval_requested', 'Mesai Onayı Bekleniyor'),
    ('ot_approved', 'Mesai Talebi Onaylandı'),
    ('ot_rejected', 'Mesai Talebi Reddedildi'),
    ('qc_review_submitted', 'KK İncelemesi Gönderildi'),
    ('qc_review_approved', 'KK İncelemesi Onaylandı'),
    ('qc_review_rejected', 'KK İncelemesi Reddedildi'),
    ('ncr_created', 'NCR Oluşturuldu'),
    ('ncr_submitted', 'NCR Onaya Gönderildi'),
    ('ncr_approved', 'NCR Onaylandı'),
    ('ncr_rejected', 'NCR Reddedildi'),
    ('ncr_assigned', 'NCR Atandı'),
    ('sales_approval_requested', 'Satış Teklifi Onay Bekliyor'),
    ('sales_approved', 'Satış Teklifi Onaylandı'),
    ('sales_rejected', 'Satış Teklifi Reddedildi'),
    ('sales_consultation', 'Satış Danışma Talebi'),
    ('sales_converted', 'Teklif İş Emrine Dönüştürüldü'),
    ('sales_order_confirmed', 'Sipariş Onayı Bildirimi'),
    ('sales_order_confirmed_notify', 'Müşteri Bilgisi'),
    ('sub_approval_requested', 'Taşeron Hakedişi Onay Bekliyor'),
    ('sub_approved', 'Taşeron Hakedişi Onaylandı'),
    ('sub_rejected', 'Taşeron Hakedişi Reddedildi'),
    ('plan_approval_requested', 'Departman Talebi Onay Bekliyor'),
    ('plan_approved', 'Departman Talebi Onaylandı'),
    ('plan_rejected', 'Departman Talebi Reddedildi'),
    ('plan_dr_approved', 'Departman Talebi Planlama Onayladı'),
    ('drawing_released', 'Çizim Yayınlandı'),
    ('release_approval_requested', 'Çizim İncelemesi Bekliyor'),
    ('release_approved', 'Çizim İncelemesi Olumlu'),
    ('release_rejected', 'Çizim İncelemesi Reddedildi'),
    ('revision_requested', 'Revizyon Talep Edildi'),
    ('revision_approved', 'Revizyon Onaylandı'),
    ('revision_completed', 'Revizyon Tamamlandı'),
    ('revision_rejected', 'Revizyon Reddedildi'),
    ('job_on_hold', 'İş Beklemede'),
    ('job_on_hold_revision', 'İş Revizyonda Beklemede'),
    ('job_resumed', 'İş Devam Ediyor'),
    ('job_date_changed', 'İş Emri Tarihi Değişti'),
    ('job_cancelled', 'İş Emri İptal Edildi'),
    ('topic_mention', 'Konuda Etiketlendiniz'),
    ('comment_mention', 'Yorumda Etiketlendiniz'),
    ('new_comment', 'Yeni Yorum'),
    ('task_assigned', 'Göreve Atandınız'),
    ('sales_consult_completed', 'Satış Destek Görevi Tamamlandı'),
    ('lc_stock_entry_complete', 'Stok Girişi Tamamlandı'),
    ('vr_approval_requested', 'İzin Talebi Onay Bekliyor'),
    ('vr_approved', 'İzin Talebi Onaylandı'),
    ('vr_rejected', 'İzin Talebi Reddedildi'),
    ('vr_cancellation_requested', 'İzin İptal Talebi Bekliyor'),
    ('vr_cancellation_approved', 'İzin İptal Talebi Onaylandı'),
    ('vr_cancellation_rejected', 'İzin İptal Talebi Reddedildi'),
    ('password_reset', 'Parola Sıfırlama Talebi'),
]


def update_notify_config(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(
        notification_type='sales_order_confirmed_notify',
    ).update(
        title_template='[Müşteri Bilgisi] {customer} – {job_no}',
        body_template=NOTIFY_BODY,
        link_template='https://ofis.gemcore.com.tr/sales/customers/?customer_id={customer_id}',
        available_vars=NOTIFY_VARS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0034_rename_customer_info_template_var'),
        ('projects', '0058_remove_customer_customer_info'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(choices=CHOICES, db_index=True, max_length=60),
        ),
        migrations.AlterField(
            model_name='notificationconfig',
            name='notification_type',
            field=models.CharField(choices=CHOICES, db_index=True, max_length=60, unique=True),
        ),
        migrations.RunPython(update_notify_config, migrations.RunPython.noop),
    ]
