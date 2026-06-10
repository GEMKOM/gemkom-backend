from django.db import migrations, models

BASE_URL = 'https://ofis.gemcore.com.tr'

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
    ('sub_approval_requested', 'Taşeron Hakedişi Onay Bekliyor'),
    ('sub_approved', 'Taşeron Hakedişi Onaylandı'),
    ('sub_rejected', 'Taşeron Hakedişi Reddedildi'),
    ('plan_approval_requested', 'Departman Talebi Onay Bekliyor'),
    ('plan_approved', 'Departman Talebi Onaylandı'),
    ('plan_rejected', 'Departman Talebi Reddedildi'),
    ('plan_dr_approved', 'Departman Talebi Planlama Onayladı'),
    ('drawing_released', 'Çizim Yayınlandı'),
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

CANCELLATION_CONFIGS = [
    {
        'notification_type': 'vr_cancellation_requested',
        'title_template': '[İptal Talebi] İzin #{vr_id} – {vr_title}',
        'body_template': (
            'Onaylanmış bir izin için iptal talebi gönderildi.\n'
            'Talep Eden: {requestor}\n'
            'Takım: {team}\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            'İptal Gerekçesi: {cancellation_reason}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/human_resources/vacation/',
        'available_vars': [
            'vr_id', 'vr_title', 'requestor', 'team', 'cancellation_reason',
            'start_date', 'end_date', 'duration_days', 'link',
        ],
    },
    {
        'notification_type': 'vr_cancellation_approved',
        'title_template': '[İptal Onaylandı] İzin #{vr_id} – {vr_title}',
        'body_template': (
            'İzin iptal talebiniz (#{vr_id}) HR tarafından onaylandı.\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            'İzin kaydınız iptal edildi ve bakiyeniz güncellendi.\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/vacation/requests/',
        'available_vars': [
            'vr_id', 'vr_title', 'requestor', 'team',
            'start_date', 'end_date', 'duration_days', 'link',
        ],
    },
    {
        'notification_type': 'vr_cancellation_rejected',
        'title_template': '[İptal Reddedildi] İzin #{vr_id} – {vr_title}',
        'body_template': (
            'İzin iptal talebiniz (#{vr_id}) HR tarafından reddedildi.\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            'İzniniz onaylı olarak devam etmektedir.\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/vacation/requests/',
        'available_vars': [
            'vr_id', 'vr_title', 'requestor', 'team',
            'start_date', 'end_date', 'duration_days', 'link',
        ],
    },
]


def add_cancellation_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in CANCELLATION_CONFIGS:
        NotificationConfig.objects.update_or_create(
            notification_type=cfg['notification_type'],
            defaults={
                'title_template': cfg['title_template'],
                'body_template': cfg['body_template'],
                'link_template': cfg['link_template'],
                'available_vars': cfg['available_vars'],
                'default_send_email': True,
                'default_send_in_app': True,
                'enabled': True,
            },
        )


def remove_cancellation_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(
        notification_type__in=[c['notification_type'] for c in CANCELLATION_CONFIGS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0028_add_vacation_notification_configs'),
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
        migrations.RunPython(
            add_cancellation_notification_configs,
            reverse_code=remove_cancellation_notification_configs,
        ),
    ]
