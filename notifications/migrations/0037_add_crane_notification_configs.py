from django.db import migrations

BASE_URL = 'https://ofis.gemcore.com.tr'

CRANE_CONFIGS = [
    {
        'notification_type': 'crane_approval_requested',
        'title_template': '[Onay Gerekli] Vinç Talebi {request_number}',
        'body_template': (
            'Vinç/platform talebi ({request_number}) için onayınız bekleniyor.\n'
            'Aşama: {stage_name} (Gerekli onay sayısı: {required_approvals})\n'
            'Talep Eden: {requestor}\n'
            'Ekipman: {crane_type}\n'
            'İş Emri: {job_no}\n'
            'Tarih: {needed_date}\n'
            'Tahmini Maliyet: {estimated_cost}\n'
            'Öncelik: {priority}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/crane-requests/pending/',
        'available_vars': [
            'cr_id', 'request_number', 'stage_name', 'required_approvals',
            'requestor', 'crane_type', 'job_no', 'needed_date',
            'estimated_cost', 'priority', 'link',
        ],
    },
    {
        'notification_type': 'crane_approved',
        'title_template': '[Vinç Talebi Onaylandı] {request_number}',
        'body_template': (
            'Vinç/platform talebi ({request_number}) onaylandı.\n'
            'Talep Eden: {requestor}\n'
            'Ekipman: {crane_type}\n'
            'İş Emri: {job_no}\n'
            'Tarih: {needed_date}\n'
            'Tahmini Maliyet: {estimated_cost}\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/crane-requests/list/',
        'available_vars': [
            'cr_id', 'request_number', 'requestor', 'crane_type', 'job_no',
            'needed_date', 'estimated_cost', 'comment', 'link',
        ],
    },
    {
        'notification_type': 'crane_rejected',
        'title_template': '[Vinç Talebi Reddedildi] {request_number}',
        'body_template': (
            'Vinç/platform talebiniz ({request_number}) reddedildi.\n'
            'Ekipman: {crane_type}\n'
            'İş Emri: {job_no}\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/crane-requests/list/',
        'available_vars': [
            'cr_id', 'request_number', 'requestor', 'crane_type', 'job_no',
            'needed_date', 'estimated_cost', 'comment', 'link',
        ],
    },
    {
        'notification_type': 'crane_completed',
        'title_template': '[Vinç Talebi Tamamlandı] {request_number}',
        'body_template': (
            'Vinç/platform talebiniz ({request_number}) tamamlandı.\n'
            'Ekipman: {crane_type}\n'
            'İş Emri: {job_no}\n'
            'Fiili Maliyet: {actual_cost}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/crane-requests/list/',
        'available_vars': [
            'cr_id', 'request_number', 'requestor', 'crane_type', 'job_no',
            'actual_cost', 'link',
        ],
    },
]


def add_crane_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in CRANE_CONFIGS:
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


def remove_crane_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(
        notification_type__in=[c['notification_type'] for c in CRANE_CONFIGS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0036_add_offer_creator_to_notify'),
    ]

    operations = [
        migrations.RunPython(
            add_crane_notification_configs,
            reverse_code=remove_crane_notification_configs,
        ),
    ]
