from django.db import migrations, models


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
    ('job_resumed', 'İş Devam Ediyor'),
    ('job_date_changed', 'İş Emri Tarihi Değişti'),
    ('topic_mention', 'Konuda Etiketlendiniz'),
    ('comment_mention', 'Yorumda Etiketlendiniz'),
    ('new_comment', 'Yeni Yorum'),
    ('task_assigned', 'Göreve Atandınız'),
    ('sales_consult_completed', 'Satış Destek Görevi Tamamlandı'),
    ('password_reset', 'Parola Sıfırlama Talebi'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0019_alter_notification_notification_type_and_more'),
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
        migrations.RunSQL(
            sql="""
            INSERT INTO notifications_notificationconfig
                (notification_type, title_template, body_template, link_template,
                 available_vars, default_send_email, default_send_in_app,
                 teams, groups, enabled, updated_at)
            VALUES (
                'job_date_changed',
                '[Termin Tarihi Değişti] {job_no}',
                '{job_no} - {job_title} iş emrinin termin tarihi güncellendi.\nEski Tarih: {previous_date}\nYeni Tarih: {new_date}\nDeğiştiren: {actor}\n\n{reason}{link}',
                'https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_no}',
                '["job_no", "job_title", "previous_date", "new_date", "actor", "reason", "link"]',
                TRUE, TRUE,
                '[]', '[]',
                TRUE,
                NOW()
            )
            ON CONFLICT (notification_type) DO NOTHING;
            """,
            reverse_sql="DELETE FROM notifications_notificationconfig WHERE notification_type = 'job_date_changed';",
        ),
    ]
