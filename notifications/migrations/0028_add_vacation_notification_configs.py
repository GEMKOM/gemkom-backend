from django.db import migrations

BASE_URL = 'https://ofis.gemcore.com.tr'

VR_CONFIGS = [
    {
        'notification_type': 'vr_approval_requested',
        'title_template': '[Onay Gerekli] İzin Talebi #{vr_id} – {vr_title}',
        'body_template': (
            'İzin talebi (#{vr_id}) için onayınız bekleniyor.\n'
            'Aşama: {stage_name} (Gerekli onay sayısı: {required_approvals})\n'
            'Talep Eden: {requestor}\n'
            'Takım: {team}\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            'Gerekçe: {reason}\n\n'
            '{link}'
        ),
        'link_template': '{approver_link}',
        'available_vars': [
            'vr_id', 'vr_title', 'stage_name', 'required_approvals',
            'requestor', 'team', 'reason', 'start_date', 'end_date',
            'duration_days', 'approver_link', 'link',
        ],
    },
    {
        'notification_type': 'vr_approved',
        'title_template': '[İzin Talebi Onaylandı] #{vr_id} – {vr_title}',
        'body_template': (
            'İzin talebiniz (#{vr_id}) onaylandı.\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/vacation/requests/',
        'available_vars': [
            'vr_id', 'vr_title', 'comment', 'requestor', 'team',
            'start_date', 'end_date', 'duration_days', 'link',
        ],
    },
    {
        'notification_type': 'vr_rejected',
        'title_template': '[İzin Talebi Reddedildi] #{vr_id} – {vr_title}',
        'body_template': (
            'İzin talebiniz (#{vr_id}) reddedildi.\n'
            'Tarih: {start_date} → {end_date} ({duration_days} gün)\n'
            '{comment}\n\n'
            '{link}'
        ),
        'link_template': f'{BASE_URL}/general/vacation/requests/',
        'available_vars': [
            'vr_id', 'vr_title', 'comment', 'requestor', 'team',
            'start_date', 'end_date', 'duration_days', 'link',
        ],
    },
]


def add_vacation_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in VR_CONFIGS:
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


def remove_vacation_notification_configs(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    NotificationConfig.objects.filter(
        notification_type__in=[c['notification_type'] for c in VR_CONFIGS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0027_alter_notificationconfig_user_groups'),
    ]

    operations = [
        migrations.RunPython(
            add_vacation_notification_configs,
            reverse_code=remove_vacation_notification_configs,
        ),
    ]
