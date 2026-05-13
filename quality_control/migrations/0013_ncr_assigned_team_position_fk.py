"""
Step 2: Add NCR.assigned_team as FK to organization.Position.
(Step 1 — removing the old Department FK — is in 0012.)
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0012_ncr_assigned_team_to_position'),
        ('organization', '0004_remove_department'),
    ]

    operations = [
        migrations.AddField(
            model_name='ncr',
            name='assigned_team',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_ncrs',
                to='organization.position',
            ),
        ),
        migrations.AddIndex(
            model_name='ncr',
            index=models.Index(fields=['assigned_team', 'status'], name='quality_con_assigne_b5d8a2_idx'),
        ),
    ]
