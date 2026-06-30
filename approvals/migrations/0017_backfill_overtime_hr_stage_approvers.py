from django.db import migrations


def _manage_hr_user_ids(apps):
    User = apps.get_model('auth', 'User')
    UserPermissionOverride = apps.get_model('users', 'UserPermissionOverride')

    direct_ids = User.objects.filter(
        is_active=True,
        user_permissions__codename='manage_hr',
        user_permissions__content_type__app_label='users',
    ).values_list('id', flat=True)
    group_ids = User.objects.filter(
        is_active=True,
        groups__permissions__codename='manage_hr',
        groups__permissions__content_type__app_label='users',
    ).values_list('id', flat=True)
    superuser_ids = User.objects.filter(
        is_active=True,
        is_superuser=True,
    ).values_list('id', flat=True)
    override_grant_ids = UserPermissionOverride.objects.filter(
        codename='manage_hr',
        granted=True,
        user__is_active=True,
    ).values_list('user_id', flat=True)
    override_deny_ids = set(UserPermissionOverride.objects.filter(
        codename='manage_hr',
        granted=False,
        user__is_active=True,
    ).values_list('user_id', flat=True))

    ids = set(direct_ids) | set(group_ids) | set(superuser_ids) | set(override_grant_ids)
    ids.difference_update(override_deny_ids)
    return sorted(ids)


def backfill_overtime_hr_stage_approvers(apps, schema_editor):
    hr_user_ids = _manage_hr_user_ids(apps)
    if not hr_user_ids:
        return

    ContentType = apps.get_model('contenttypes', 'ContentType')
    OvertimeRequest = apps.get_model('overtime', 'OvertimeRequest')
    ApprovalStageInstance = apps.get_model('approvals', 'ApprovalStageInstance')

    overtime_ct = ContentType.objects.get_for_model(OvertimeRequest)
    ApprovalStageInstance.objects.filter(
        workflow__content_type=overtime_ct,
        workflow__policy__subject_type='overtime_request',
        workflow__is_complete=False,
        workflow__is_rejected=False,
        workflow__is_cancelled=False,
        order=2,
        is_complete=False,
        is_rejected=False,
        approver_user_ids=[],
    ).update(approver_user_ids=hr_user_ids)


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0016_approvallstage_role_user_group'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('overtime', '0004_remove_team_index'),
        ('users', '0043_add_machining_performance_report_permission'),
    ]

    operations = [
        migrations.RunPython(backfill_overtime_hr_stage_approvers, migrations.RunPython.noop),
    ]
