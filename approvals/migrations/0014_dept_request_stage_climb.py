from django.db import migrations


def set_climb_levels(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    policy = ApprovalPolicy.objects.filter(subject_type='department_request').first()
    if policy:
        ApprovalStage.objects.filter(policy=policy, order=1).update(climb_levels=1)


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0013_remove_approvalpolicy_priority_in'),
    ]

    operations = [
        migrations.RunPython(set_climb_levels, migrations.RunPython.noop),
    ]
