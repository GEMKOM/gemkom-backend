from django.db import migrations, models


def retire_old_paint_assignments(apps, schema_editor):
    """
    Mark all assignments whose department_task is a painting main task
    (task_type='painting', parent_id IS NULL) as retired.
    These are the old auto-created assignments that must not appear in
    future statement generation.
    """
    SubcontractingAssignment = apps.get_model('subcontracting', 'SubcontractingAssignment')
    SubcontractingAssignment.objects.filter(
        department_task__task_type='painting',
        department_task__parent__isnull=True,
    ).update(is_retired=True)


class Migration(migrations.Migration):

    dependencies = [
        ('subcontracting', '0006_add_employee_count_to_statement'),
    ]

    operations = [
        migrations.AddField(
            model_name='subcontractingassignment',
            name='is_retired',
            field=models.BooleanField(
                default=False,
                help_text='Retired assignments are excluded from future statement generation.',
            ),
        ),
        migrations.RunPython(
            retire_old_paint_assignments,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
