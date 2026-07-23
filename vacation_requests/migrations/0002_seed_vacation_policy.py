from django.db import migrations


def seed_vacation_policy(apps, schema_editor):
    ApprovalPolicy = apps.get_model("approvals", "ApprovalPolicy")
    ApprovalStage  = apps.get_model("approvals", "ApprovalStage")
    Group          = apps.get_model("auth", "Group")

    policy, created = ApprovalPolicy.objects.get_or_create(
        name="Vacation – Default",
        # NOTE: is_rolling_mill / priority_in used to be seeded here, but those
        # fields were added in approvals 0004/0005 and removed again in
        # 0012/0013 — this migration's historical model state (approvals 0001)
        # never had them, so seeding them breaks fresh databases.
        defaults={
            "is_active":          True,
            "selection_priority": 10,
        },
    )

    if created or not policy.stages.exists():
        stage1 = ApprovalStage.objects.create(
            policy=policy,
            order=1,
            name="Takım Müdürü",
            required_approvals=1,
        )

        stage2 = ApprovalStage.objects.create(
            policy=policy,
            order=2,
            name="İnsan Kaynakları",
            required_approvals=1,
        )

        # approver_groups was removed in approvals 0009 (after 0008 expanded
        # groups into approver_users); in a fresh database this migration runs
        # after that removal, so the historical model may not have the field.
        hr_group = Group.objects.filter(name="hr_team").first()
        if hr_group and hasattr(stage2, "approver_groups"):
            stage2.approver_groups.add(hr_group)


def remove_vacation_policy(apps, schema_editor):
    ApprovalPolicy = apps.get_model("approvals", "ApprovalPolicy")
    ApprovalPolicy.objects.filter(name="Vacation – Default").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("vacation_requests", "0001_initial"),
        ("approvals", "0001_initial"),
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_vacation_policy, remove_vacation_policy),
    ]
