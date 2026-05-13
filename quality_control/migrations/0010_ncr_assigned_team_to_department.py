"""
Change NCR.assigned_team from FK(auth.Group) to FK(organization.Department).

The old "group → department" mapping is 1:1 (machining_team → machining, etc.)
We translate each existing assigned_team Group name back to a dept code and
set the new FK.  NCRs whose group has no matching department get assigned_team=NULL.
"""
from django.db import migrations, models
import django.db.models.deletion


# Maps old group names to the new department codes (from organization seed data)
GROUP_TO_DEPT = {
    'machining_team':       'machining',
    'design_team':          'design',
    'logistics_team':       'logistics',
    'procurement_team':     'procurement',
    'welding_team':         'welding',
    'planning_team':        'planning',
    'manufacturing_team':   'manufacturing',
    'maintenance_team':     'maintenance',
    'qualitycontrol_team':  'qualitycontrol',
    'cutting_team':         'cutting',
    'warehouse_team':       'warehouse',
    'finance_team':         'finance',
    'management_team':      'management',
    'hr_team':              'human_resources',
    'sales_team':           'sales',
    'accounting_team':      'accounting',
}


def migrate_group_to_department(apps, schema_editor):
    NCR = apps.get_model('quality_control', 'NCR')
    Department = apps.get_model('organization', 'Department')

    dept_cache = {}
    for ncr in NCR.objects.filter(assigned_team_group__isnull=False).select_related('assigned_team_group'):
        group_name = ncr.assigned_team_group.name
        dept_code = GROUP_TO_DEPT.get(group_name)
        if not dept_code:
            continue
        if dept_code not in dept_cache:
            dept_cache[dept_code] = Department.objects.filter(code=dept_code).first()
        dept = dept_cache[dept_code]
        if dept:
            ncr.assigned_team = dept
            ncr.save(update_fields=['assigned_team'])


def reverse_migrate(apps, schema_editor):
    NCR = apps.get_model('quality_control', 'NCR')
    Group = apps.get_model('auth', 'Group')
    DEPT_TO_GROUP = {v: k for k, v in GROUP_TO_DEPT.items()}

    group_cache = {}
    for ncr in NCR.objects.filter(assigned_team__isnull=False).select_related('assigned_team'):
        dept_code = ncr.assigned_team.code
        group_name = DEPT_TO_GROUP.get(dept_code)
        if not group_name:
            continue
        if group_name not in group_cache:
            group_cache[group_name] = Group.objects.filter(name=group_name).first()
        group = group_cache[group_name]
        if group:
            ncr.assigned_team_group = group
            ncr.save(update_fields=['assigned_team_group'])


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0009_backfill_qcreview_discussion_topics'),
        ('organization', '0003_seed_positions_and_permissions'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # 1. Rename existing Group FK to temp name
        migrations.RenameField(
            model_name='ncr',
            old_name='assigned_team',
            new_name='assigned_team_group',
        ),
        # 2. Add new Department FK (nullable) with the original name
        migrations.AddField(
            model_name='ncr',
            name='assigned_team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_ncrs',
                to='organization.department',
            ),
        ),
        # 3. Migrate data
        migrations.RunPython(migrate_group_to_department, reverse_migrate),
        # 4. Drop the old Group FK
        migrations.RemoveField(
            model_name='ncr',
            name='assigned_team_group',
        ),
        migrations.AlterIndexTogether(
            name='ncr',
            index_together=set(),
        ),
    ]
