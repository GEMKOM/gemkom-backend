from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from approvals.models import ApprovalPolicy, ApprovalStage
from approvals.resolvers import resolve_approvers_for_stage
from users.models import UserProfile


class ResolveApproversForStageTests(TestCase):
    def setUp(self):
        content_type = ContentType.objects.get_for_model(UserProfile)
        self.manage_hr_permission, _ = Permission.objects.get_or_create(
            codename="manage_hr",
            content_type=content_type,
            defaults={"name": "Can manage HR"},
        )

    def _create_stage(self, subject_type):
        policy = ApprovalPolicy.objects.create(
            name=f"{subject_type} policy",
            subject_type=subject_type,
            is_active=True,
        )
        return ApprovalStage.objects.create(
            policy=policy,
            order=2,
            name="HR",
            required_approvals=1,
        )

    def test_overtime_stage_two_falls_back_to_manage_hr_users(self):
        requester = User.objects.create_user(username="requester")
        hr_user = User.objects.create_user(username="hr-user")
        hr_user.user_permissions.add(self.manage_hr_permission)

        stage = self._create_stage("overtime_request")

        self.assertEqual(resolve_approvers_for_stage(stage, requester), [hr_user.id])

    def test_unrelated_stage_two_does_not_fall_back_to_manage_hr_users(self):
        requester = User.objects.create_user(username="requester")
        hr_user = User.objects.create_user(username="hr-user")
        hr_user.user_permissions.add(self.manage_hr_permission)

        stage = self._create_stage("purchase_request")

        self.assertEqual(resolve_approvers_for_stage(stage, requester), [])
