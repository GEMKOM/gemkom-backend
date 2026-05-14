"""
Replace NCR.assigned_team FK from organization.Position to organization.UserGroup.
Existing data: assigned_team pointed at a Position whose department_code can be mapped
to a UserGroup by name. Any unmapped positions are set to NULL.
"""
from django.db import migrations, models
import django.db.models.deletion


DEPT_CODE_TO_GROUP_NAME = {
    'design':        'Dizayn',
    'planning':      'Planlama',
    'procurement':   'Satın Alma',
    'manufacturing': 'İmalat',
    'logistics':     'Lojistik',
    'painting':      'İmalat',
    'qualitycontrol': 'Kalite Kontrol',
    'maintenance':   None,  # no group; set to NULL
}


def migrate_assigned_team(apps, schema_editor):
    NCR = apps.get_model('quality_control', 'NCR')
    UserGroup = apps.get_model('organization', 'UserGroup')

    group_cache: dict[str, object] = {}
    for ncr in NCR.objects.select_related('assigned_team_position').filter(assigned_team_position__isnull=False):
        dept_code = ncr.assigned_team_position.department_code
        group_name = DEPT_CODE_TO_GROUP_NAME.get(dept_code)
        if not group_name:
            ncr.assigned_team_group = None
        else:
            if group_name not in group_cache:
                group_cache[group_name] = UserGroup.objects.filter(name=group_name, is_active=True).first()
            ncr.assigned_team_group = group_cache[group_name]
        ncr.save(update_fields=['assigned_team_group'])


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0013_ncr_assigned_team_position_fk'),
        ('organization', '0005_usergroup'),
    ]

    operations = [
        # Step 1: rename the existing position FK column so we can backfill from it
        migrations.RenameField(
            model_name='ncr',
            old_name='assigned_team',
            new_name='assigned_team_position',
        ),
        # Step 2: add new UserGroup FK
        migrations.AddField(
            model_name='ncr',
            name='assigned_team_group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_ncrs',
                to='organization.usergroup',
            ),
        ),
        # Step 3: backfill
        migrations.RunPython(migrate_assigned_team, migrations.RunPython.noop),
        # Step 4: drop old position FK and its index
        migrations.RemoveIndex(
            model_name='ncr',
            name='quality_con_assigne_b5d8a2_idx',
        ),
        migrations.RemoveField(
            model_name='ncr',
            name='assigned_team_position',
        ),
        # Step 5: rename new column to assigned_team
        migrations.RenameField(
            model_name='ncr',
            old_name='assigned_team_group',
            new_name='assigned_team',
        ),
        migrations.AddIndex(
            model_name='ncr',
            index=models.Index(fields=['assigned_team', 'status'], name='quality_con_assigne_b5d8a2_idx'),
        ),
    ]
