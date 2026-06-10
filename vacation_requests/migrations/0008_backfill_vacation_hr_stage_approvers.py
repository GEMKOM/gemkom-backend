"""
Backfill empty HR approver lists on open vacation approval workflows.

The vacation policy's HR stage lost its approver resolution when
role_department_code was removed in favour of role_user_group without a
migration for vacation/overtime HR stages.
"""
from django.db import migrations


def _hr_user_ids(User):
    return list(
        User.objects.filter(is_active=True, groups__name="hr_team")
        .values_list("id", flat=True)
        .distinct()
    )


def backfill_hr_stage_approvers(apps, schema_editor):
    ApprovalStageInstance = apps.get_model("approvals", "ApprovalStageInstance")
    ApprovalWorkflow = apps.get_model("approvals", "ApprovalWorkflow")
    ContentType = apps.get_model("contenttypes", "ContentType")
    VacationRequest = apps.get_model("vacation_requests", "VacationRequest")
    User = apps.get_model("auth", "User")

    hr_ids = _hr_user_ids(User)
    if not hr_ids:
        return

    ct = ContentType.objects.get_for_model(VacationRequest)
    open_wf_ids = ApprovalWorkflow.objects.filter(
        content_type=ct,
        is_complete=False,
        is_rejected=False,
        is_cancelled=False,
    ).values_list("id", flat=True)

    for stage in ApprovalStageInstance.objects.filter(
        workflow_id__in=open_wf_ids,
        order=2,
        is_complete=False,
        is_rejected=False,
    ):
        if stage.approver_user_ids:
            continue
        stage.approver_user_ids = hr_ids
        stage.required_approvals = min(stage.required_approvals or 1, len(hr_ids)) or 1
        stage.save(update_fields=["approver_user_ids", "required_approvals"])


class Migration(migrations.Migration):

    dependencies = [
        ("vacation_requests", "0007_add_company_holiday_and_cancellation_status"),
        ("approvals", "0016_approvallstage_role_user_group"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(backfill_hr_stage_approvers, migrations.RunPython.noop),
    ]
