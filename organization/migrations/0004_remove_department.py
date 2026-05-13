"""
Remove the Department model entirely.

Steps:
1. Add department_code SlugField to Position
2. Copy position.department.code → position.department_code for all rows
3. Remove position.department FK
4. Update Position.Meta.ordering
5. Delete the Department table
"""
from django.db import migrations, models


def copy_dept_codes(apps, schema_editor):
    Position = apps.get_model('organization', 'Position')
    for pos in Position.objects.select_related('department').filter(department__isnull=False):
        pos.department_code = pos.department.code
        pos.save(update_fields=['department_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0003_seed_positions_and_permissions'),
        ('quality_control', '0012_ncr_assigned_team_to_position'),
    ]

    operations = [
        # 1. Add the new field
        migrations.AddField(
            model_name='position',
            name='department_code',
            field=models.SlugField(
                blank=True,
                default='',
                help_text="Logical department grouping slug (e.g. 'machining', 'human_resources'). No FK — just a tag.",
                max_length=50,
            ),
        ),

        # 2. Backfill department_code from the FK
        migrations.RunPython(copy_dept_codes, migrations.RunPython.noop),

        # 3. Remove the department FK from Position
        migrations.RemoveField(
            model_name='position',
            name='department',
        ),

        # 4. Update ordering on Position (no AlterModelOptions needed — Django handles it)
        migrations.AlterModelOptions(
            name='position',
            options={
                'ordering': ['level', 'department_code', 'title'],
                'verbose_name': 'Pozisyon',
                'verbose_name_plural': 'Pozisyonlar',
            },
        ),

        # 5. Delete the Department table
        migrations.DeleteModel(
            name='Department',
        ),
    ]
