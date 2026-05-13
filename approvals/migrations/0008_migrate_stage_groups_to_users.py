"""
Data migration: expand ApprovalStage.approver_groups into explicit approver_users.

Any existing stage that references Django Groups has those groups expanded to
their current active members, which are then added to approver_users. This
preserves procurement approval behavior exactly — the static group memberships
at the time of this migration become the new static user list.

After this migration runs, approver_groups can be safely removed.
"""
from django.db import migrations


def expand_groups_to_users(apps, schema_editor):
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    User = apps.get_model('auth', 'User')

    for stage in ApprovalStage.objects.prefetch_related('approver_groups', 'approver_users').all():
        groups = stage.approver_groups.all()
        if not groups.exists():
            continue
        new_user_ids = set(stage.approver_users.values_list('id', flat=True))
        for group in groups:
            member_ids = User.objects.filter(
                groups=group, is_active=True
            ).values_list('id', flat=True)
            new_user_ids.update(member_ids)
        stage.approver_users.set(list(new_user_ids))


def reverse_noop(apps, schema_editor):
    pass  # irreversible — group membership may have changed


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0007_approval_stage_org_fields'),
    ]

    operations = [
        migrations.RunPython(expand_groups_to_users, reverse_noop),
    ]
