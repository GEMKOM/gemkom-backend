from django.db import migrations

def seed_default_policy(apps, schema_editor):
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalStage = apps.get_model('approvals', 'ApprovalStage')
    Group = apps.get_model('auth', 'Group')

    policy, _ = ApprovalPolicy.objects.get_or_create(
        name="Default Policy",
        defaults={"is_active": True, "selection_priority": 10, "priority_in": []},
    )
    lead_group, _ = Group.objects.get_or_create(name="Team Leads")
    finance_group, _ = Group.objects.get_or_create(name="Finance Approvers")

    s1, _ = ApprovalStage.objects.get_or_create(
        policy=policy, order=1,
        defaults={"name": "Team Lead Approval", "required_approvals": 1},
    )
    s1.approver_groups.add(lead_group)

    s2, _ = ApprovalStage.objects.get_or_create(
        policy=policy, order=2,
        defaults={"name": "Finance Approval", "required_approvals": 1},
    )
    s2.approver_groups.add(finance_group)

def unseed_default_policy(apps, schema_editor):
    # Usually keep seeded data; but if you want a reversible migration:
    ApprovalPolicy = apps.get_model('approvals', 'ApprovalPolicy')
    ApprovalPolicy.objects.filter(name="Default Policy").delete()

class Migration(migrations.Migration):
    dependencies = [
        ('approvals', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),  # ensure auth groups exist
    ]
    operations = [
        migrations.RunPython(seed_default_policy, reverse_code=unseed_default_policy),
    ]
