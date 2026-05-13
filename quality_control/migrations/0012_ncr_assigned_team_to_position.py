"""
Step 1: Remove NCR.assigned_team FK to Department (before Department is deleted).
Step 2 is in 0013: add new FK to Position (after Department is gone).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('quality_control', '0011_remove_ncr_quality_con_assigne_b5d8a2_idx_and_more'),
        ('organization', '0003_seed_positions_and_permissions'),
    ]

    operations = [
        # Remove the index that references assigned_team
        migrations.RemoveIndex(
            model_name='ncr',
            name='quality_con_assigne_b5d8a2_idx',
        ),
        # Drop the Department FK column entirely
        migrations.RemoveField(
            model_name='ncr',
            name='assigned_team',
        ),
    ]
