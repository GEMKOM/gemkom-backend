from django.db import migrations


def set_role_user_group(apps, schema_editor):
    """
    The previous migration (0015) attempted to set a non-existent field
    `role_department_code` on ApprovalStage.  This migration corrects the
    NCR and QC Review approval stages by pointing their first stage at the
    matching UserGroup (looked up by name/slug) instead.

    If no matching UserGroup exists yet, the stage is left unchanged —
    an admin can configure it manually via the Approvals UI.
    """
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    UserGroup = apps.get_model('organization', 'UserGroup')

    # Candidate slugs/names for the quality-control user group.
    qc_group_candidates = ['qualitycontrol', 'quality-control', 'quality_control', 'Kalite Kontrol']

    qc_group = None
    for candidate in qc_group_candidates:
        qc_group = (
            UserGroup.objects.filter(slug=candidate).first()
            or UserGroup.objects.filter(name__iexact=candidate).first()
        )
        if qc_group:
            break

    if not qc_group:
        # No matching group found — leave stages unchanged.
        # Admin must assign role_user_group manually.
        return

    for subject_type in ('qc_review', 'ncr'):
        policy = ApprovalPolicy.objects.filter(subject_type=subject_type).first()
        if policy:
            ApprovalStage.objects.filter(policy=policy, order=1).update(
                role_user_group=qc_group,
                climb_levels=None,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('approvals', '0015_qc_ncr_stage_role_dept'),
        ('organization', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(set_role_user_group, migrations.RunPython.noop),
    ]
