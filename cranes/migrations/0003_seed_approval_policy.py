"""
Seed the default approval policy for crane requests: a single climb-based
stage that resolves to the requester's department manager (same shape as
the department-request policy). Stages remain editable in the approvals
admin UI.
"""
from django.db import migrations

POLICY_NAME = 'Vinç Talebi – Varsayılan'
SUBJECT_TYPE = 'crane_request'


def seed(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')

    policy, _ = ApprovalPolicy.objects.get_or_create(
        name=POLICY_NAME,
        defaults={
            'subject_type': SUBJECT_TYPE,
            'is_active': True,
            'selection_priority': 100,
        },
    )
    ApprovalStage.objects.get_or_create(
        policy=policy,
        order=1,
        defaults={
            'name': 'Departman Yöneticisi Onayı',
            'required_approvals': 1,
            'climb_levels': 1,
        },
    )


def unseed(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalPolicy.objects.filter(name=POLICY_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cranes', '0002_seed_types_rates_group'),
        ('approvals', '0016_approvallstage_role_user_group'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
