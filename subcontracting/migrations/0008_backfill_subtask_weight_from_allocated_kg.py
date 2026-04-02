from django.db import migrations


def backfill_subtask_weights(apps, schema_editor):
    """
    Set each subcontracting subtask's weight to round(allocated_weight_kg),
    matching the new behaviour where weight mirrors the assignment's kg allocation.

    Only touches tasks with task_type='subcontracting' that have an assignment.
    Skips any assignment whose allocated_weight_kg rounds to 0 (safety guard).
    """
    SubcontractingAssignment = apps.get_model('subcontracting', 'SubcontractingAssignment')
    JobOrderDepartmentTask = apps.get_model('projects', 'JobOrderDepartmentTask')

    for assignment in SubcontractingAssignment.objects.select_related('department_task').filter(
        department_task__task_type='subcontracting'
    ):
        new_weight = max(1, round(assignment.allocated_weight_kg))
        task = assignment.department_task
        if task.weight != new_weight:
            JobOrderDepartmentTask.objects.filter(pk=task.pk).update(weight=new_weight)


class Migration(migrations.Migration):

    dependencies = [
        ('subcontracting', '0007_assignment_is_retired'),
        ('projects', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            backfill_subtask_weights,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
