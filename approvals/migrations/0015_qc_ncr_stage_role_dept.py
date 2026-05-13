from django.db import migrations


def set_role_dept(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    for subject_type in ('qc_review', 'ncr'):
        policy = ApprovalPolicy.objects.filter(subject_type=subject_type).first()
        if policy:
            ApprovalStage.objects.filter(policy=policy, order=1).update(
                role_department_code='qualitycontrol'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0014_dept_request_stage_climb'),
    ]

    operations = [
        migrations.RunPython(set_role_dept, migrations.RunPython.noop),
    ]
