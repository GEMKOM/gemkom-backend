from django.db import migrations, models
import django.db.models.deletion

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


def migrate_assigned_team_to_fk(apps, schema_editor):
    NCR = apps.get_model('quality_control', 'NCR')
    Group = apps.get_model('auth', 'Group')

    group_cache = {}
    for ncr in NCR.objects.exclude(assigned_team_old='').exclude(assigned_team_old__isnull=True):
        team_code = ncr.assigned_team_old
        group_name = TEAM_TO_GROUP.get(team_code)
        if not group_name:
            continue
        if group_name not in group_cache:
            group_cache[group_name] = Group.objects.filter(name=group_name).first()
        group = group_cache[group_name]
        if group:
            ncr.assigned_team = group
            ncr.save(update_fields=['assigned_team'])


def reverse_migrate(apps, schema_editor):
    NCR = apps.get_model('quality_control', 'NCR')
    GROUP_TO_TEAM = {v: k for k, v in TEAM_TO_GROUP.items()}
    for ncr in NCR.objects.filter(assigned_team__isnull=False):
        team_code = GROUP_TO_TEAM.get(ncr.assigned_team.name, '')
        ncr.assigned_team_old = team_code
        ncr.save(update_fields=['assigned_team_old'])


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0005_add_ncrfile'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # 1. Rename old CharField to a temp name so we can add the new FK with the real name
        migrations.RenameField(
            model_name='ncr',
            old_name='assigned_team',
            new_name='assigned_team_old',
        ),
        # 2. Add new FK column (nullable)
        migrations.AddField(
            model_name='ncr',
            name='assigned_team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_ncrs',
                to='auth.group',
            ),
        ),
        # 3. Copy data
        migrations.RunPython(migrate_assigned_team_to_fk, reverse_code=reverse_migrate),
        # 4. Drop the old char field
        migrations.RemoveField(
            model_name='ncr',
            name='assigned_team_old',
        ),
        # 5. Replace the old index with one on the FK column
        migrations.AlterIndexTogether(
            name='ncr',
            index_together=set(),
        ),
    ]
