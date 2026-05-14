from django.db import migrations, models
import django.db.models.deletion


def migrate_role_dept_to_group(apps, schema_editor):
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    UserGroup = apps.get_model('organization', 'UserGroup')

    qc_group = UserGroup.objects.filter(name='Kalite Kontrol', is_active=True).first()
    if qc_group:
        ApprovalStage.objects.filter(role_department_code='qualitycontrol').update(
            role_user_group=qc_group,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0015_qc_ncr_stage_role_dept'),
        ('organization', '0005_usergroup'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalstage',
            name='role_user_group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='approval_stages',
                to='organization.usergroup',
                help_text='When set, resolve approvers to all active members of this UserGroup (ignores climb_levels).',
            ),
        ),
        migrations.RunPython(migrate_role_dept_to_group, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='approvalstage',
            name='role_department_code',
        ),
    ]
