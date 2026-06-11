from django.db import migrations

UPDATED_CONFIGS = [
    {
        'notification_type': 'release_approval_requested',
        'title_template': '[Akran İncelemesi] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} yeni teknik çizim yayını oluşturdu ve akran incelemenizi bekliyor.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            'Klasör Yolu:\n{folder_path}\n\n'
            'Değişiklikler:\n{changelog}\n\n'
            '{link}'
        ),
    },
    {
        'notification_type': 'release_approved',
        'title_template': '[Akran İncelemesi Olumlu] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} teknik çizim yayınınızı olumlu değerlendirdi.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            '{link}'
        ),
    },
    {
        'notification_type': 'release_rejected',
        'title_template': '[Çizim Reddedildi] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} teknik çizim yayınınızı reddetti.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            'Red Nedeni:\n{reason}\n\n'
            '{link}'
        ),
    },
]

PREVIOUS_CONFIGS = [
    {
        'notification_type': 'release_approval_requested',
        'title_template': '[Çizim Onay Bekliyor] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} yeni teknik çizim yayını oluşturdu ve onayınızı bekliyor.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            'Klasör Yolu:\n{folder_path}\n\n'
            'Değişiklikler:\n{changelog}\n\n'
            '{link}'
        ),
    },
    {
        'notification_type': 'release_approved',
        'title_template': '[Çizim Onayı] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} teknik çizim yayınınızı onayladı.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            '{link}'
        ),
    },
    {
        'notification_type': 'release_rejected',
        'title_template': '[Çizim Reddedildi] {job_no} Rev.{revision}',
        'body_template': (
            '{actor} teknik çizim yayınınızı reddetti.\n'
            'İş Emri: {job_no} - {job_title}\n'
            'Revizyon: {revision}\n\n'
            'Red Nedeni:\n{reason}\n\n'
            '{link}'
        ),
    },
]


def update_templates(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in UPDATED_CONFIGS:
        NotificationConfig.objects.filter(
            notification_type=cfg['notification_type'],
        ).update(
            title_template=cfg['title_template'],
            body_template=cfg['body_template'],
        )


def revert_templates(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in PREVIOUS_CONFIGS:
        NotificationConfig.objects.filter(
            notification_type=cfg['notification_type'],
        ).update(
            title_template=cfg['title_template'],
            body_template=cfg['body_template'],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0030_add_release_approval_notifications'),
    ]

    operations = [
        migrations.RunPython(update_templates, revert_templates),
    ]
