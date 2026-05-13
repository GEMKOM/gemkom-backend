"""
Data migration: wire up org-tree-based approver resolution on the default
Vacation and Overtime approval policies.

  Stage 1 → climb_levels=1  (direct manager, skipping vacant positions)
  Stage 2 → role_department_code='human_resources'

Policies are looked up by name; if they don't exist yet (fresh install) the
migration is a no-op for that policy.
"""
from django.db import migrations


def set_stage_rules(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')

    targets = [
        'Vacation – Default',
        'Overtime – Default',
        # also handle ASCII dash variants in case the DB used them
        'Vacation - Default',
        'Overtime - Default',
    ]

    for policy_name in targets:
        try:
            policy = ApprovalPolicy.objects.get(name=policy_name)
        except ApprovalPolicy.DoesNotExist:
            continue

        stage1 = ApprovalStage.objects.filter(policy=policy, order=1).first()
        if stage1:
            stage1.climb_levels = 1
            stage1.role_department_code = ''
            stage1.save(update_fields=['climb_levels', 'role_department_code'])

        stage2 = ApprovalStage.objects.filter(policy=policy, order=2).first()
        if stage2:
            stage2.climb_levels = None
            stage2.role_department_code = 'human_resources'
            stage2.save(update_fields=['climb_levels', 'role_department_code'])


def reverse_stage_rules(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')

    targets = [
        'Vacation – Default', 'Overtime – Default',
        'Vacation - Default', 'Overtime - Default',
    ]
    for policy_name in targets:
        try:
            policy = ApprovalPolicy.objects.get(name=policy_name)
        except ApprovalPolicy.DoesNotExist:
            continue
        ApprovalStage.objects.filter(policy=policy, order__in=[1, 2]).update(
            climb_levels=None,
            role_department_code='',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0009_remove_approver_groups'),
    ]

    operations = [
        migrations.RunPython(set_stage_rules, reverse_stage_rules),
    ]
