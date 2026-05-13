from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0006_alter_prapprovalstageinstance_unique_together_and_more'),
        ('organization', '0003_seed_positions_and_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='approvalstage',
            name='climb_levels',
            field=models.PositiveSmallIntegerField(
                null=True, blank=True,
                help_text='Walk N levels up the requester\'s position tree to find approvers. Vacant positions are skipped.',
            ),
        ),
        migrations.AddField(
            model_name='approvalstage',
            name='role_department_code',
            field=models.SlugField(
                null=True, blank=True,
                help_text="When set, resolve approvers to all active users in this department (ignores climb_levels). E.g. 'human_resources' for an HR stage.",
            ),
        ),
    ]
