from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0008_migrate_stage_groups_to_users'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='approvalstage',
            name='approver_groups',
        ),
    ]
