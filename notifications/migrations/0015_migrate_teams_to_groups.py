from django.db import migrations

TEAM_TO_GROUP = {
    'machining':          'machining_team',
    'design':             'design_team',
    'logistics':          'logistics_team',
    'procurement':        'procurement_team',
    'welding':            'welding_team',
    'planning':           'planning_team',
    'manufacturing':      'manufacturing_team',
    'maintenance':        'maintenance_team',
    'rollingmill':        'manufacturing_team',
    'qualitycontrol':     'qualitycontrol_team',
    'cutting':            'cutting_team',
    'warehouse':          'warehouse_team',
    'finance':            'finance_team',
    'management':         'management_team',
    'external_workshops': 'procurement_team',
    'human_resouces':     'hr_team',
    'sales':              'sales_team',
    'accounting':         'accounting_team',
}


def migrate_teams_to_groups(apps, schema_editor):
    NotificationConfig = apps.get_model('notifications', 'NotificationConfig')
    for cfg in NotificationConfig.objects.exclude(teams=[]):
        converted = [TEAM_TO_GROUP[t] for t in cfg.teams if t in TEAM_TO_GROUP]
        if converted:
            merged = list(dict.fromkeys(cfg.groups + converted))  # deduplicate, preserve order
            cfg.groups = merged
        cfg.teams = []
        cfg.save(update_fields=['teams', 'groups'])


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0014_notificationconfig_add_groups'),
    ]

    operations = [
        migrations.RunPython(migrate_teams_to_groups, migrations.RunPython.noop),
    ]
