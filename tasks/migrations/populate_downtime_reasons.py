# Generated migration to populate default downtime reasons
# Run this after creating the DowntimeReason model migration

from django.db import migrations


def populate_downtime_reasons(apps, schema_editor):
    """Create default downtime reasons for operators to select from"""
    DowntimeReason = apps.get_model('tasks', 'DowntimeReason')

    # Define default reasons with their properties
    reasons = [
        # Breaks and personal time
        {
            'code': 'LUNCH',
            'name': 'Yemek Molası',
            'category': 'break',
            'creates_timer': True,
            'requires_fault_reference': False,
            'display_order': 1,
        },
        {
            'code': 'BREAK',
            'name': 'Kısa mola',
            'category': 'break',
            'creates_timer': True,
            'requires_fault_reference': False,
            'display_order': 2,
        },
        {
            'code': 'END_SHIFT',
            'name': 'Mesai Sonu',
            'category': 'break',
            'creates_timer': False,  # Don't create timer when going home
            'requires_fault_reference': False,
            'display_order': 3,
        },

        # Downtime/waiting reasons
        {
            'code': 'WAITING_MATERIALS',
            'name': 'Malzeme Bekleniyor',
            'category': 'downtime',
            'creates_timer': True,
            'requires_fault_reference': False,
            'display_order': 10,
        },
        {
            'code': 'WAITING_TOOLS',
            'name': 'Ekipman Bekleniyor',
            'category': 'downtime',
            'creates_timer': True,
            'requires_fault_reference': False,
            'display_order': 11,
        },
        {
            'code': 'MACHINE_FAULT',
            'name': 'Arıza',
            'category': 'downtime',
            'creates_timer': True,
            'requires_fault_reference': True,
            'display_order': 12,
        },
        {
            'code': 'OTHER',
            'name': 'Diğer',
            'category': 'downtime',
            'creates_timer': True,
            'requires_fault_reference': False,
            'display_order': 99,
        },

        # Work complete
        {
            'code': 'WORK_COMPLETE',
            'name': 'Parça İşlemesi Tamamlandı',
            'category': 'complete',
            'creates_timer': False,  # Don't create timer when operation is done
            'requires_fault_reference': False,
            'display_order': 100,
        },
    ]

    # Create reasons (only if they don't exist)
    for reason_data in reasons:
        DowntimeReason.objects.get_or_create(
            code=reason_data['code'],
            defaults=reason_data
        )


def reverse_populate(apps, schema_editor):
    """Remove default downtime reasons if migration is reversed"""
    DowntimeReason = apps.get_model('tasks', 'DowntimeReason')

    default_codes = [
        'LUNCH', 'BREAK', 'END_SHIFT',
        'WAITING_MATERIALS', 'WAITING_TOOLS', 'MACHINE_FAULT', 'SETUP', 'OTHER',
        'WORK_COMPLETE'
    ]

    DowntimeReason.objects.filter(code__in=default_codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        # Depends on the migration that creates the DowntimeReason model
        ('tasks', '0007_timer_related_fault_timer_timer_type_downtimereason_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_downtime_reasons, reverse_populate),
    ]
