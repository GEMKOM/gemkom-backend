# Reconstructed to match a migration already applied to the production database
# (applied 2026-03-06) whose file was missing from this branch. It adds the
# OvertimeEntry.operations M2M to tasks.Operation. Kept as its own migration so
# the code migration graph matches the deployed schema.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('overtime', '0003_alter_overtimeentry_user'),
        ('tasks', '0005_part_operation_tool_operationtool_operation_tools_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='overtimeentry',
            name='operations',
            field=models.ManyToManyField(blank=True, related_name='overtime_entries', to='tasks.operation'),
        ),
    ]
