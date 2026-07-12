from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from approvals.models import ApprovalPolicy, ApprovalStageInstance, ApprovalWorkflow
from approvals.services import record_decision
from planning.models import DepartmentRequest


class RecordDecisionPermissionTests(TestCase):
    def setUp(self):
        self.requestor = User.objects.create_user(username="requestor", password="pw")
        self.approver = User.objects.create_user(username="approver", password="pw")
        self.outsider = User.objects.create_user(username="outsider", password="pw")
        self.policy = ApprovalPolicy.objects.create(
            name="Department request policy",
            subject_type="department_request",
        )
        self.department_request = DepartmentRequest.objects.create(
            title="Needs approval",
            description="",
            department="machining",
            requestor=self.requestor,
            status="submitted",
        )
        content_type = ContentType.objects.get_for_model(DepartmentRequest)
        self.workflow = ApprovalWorkflow.objects.create(
            content_type=content_type,
            object_id=self.department_request.id,
            policy=self.policy,
            current_stage_order=1,
        )
        self.stage = ApprovalStageInstance.objects.create(
            workflow=self.workflow,
            order=1,
            name="Manager",
            required_approvals=1,
            approver_user_ids=[self.approver.id],
        )

    def test_rejects_user_who_is_not_current_stage_approver(self):
        with self.assertRaises(PermissionError):
            record_decision(self.department_request, self.outsider, approve=True)

        self.stage.refresh_from_db()
        self.workflow.refresh_from_db()
        self.assertEqual(self.stage.approved_count, 0)
        self.assertFalse(self.stage.is_complete)
        self.assertFalse(self.workflow.is_complete)

    def test_allows_current_stage_approver(self):
        _, _, outcome = record_decision(self.department_request, self.approver, approve=True)

        self.stage.refresh_from_db()
        self.workflow.refresh_from_db()
        self.assertEqual(outcome, "completed")
        self.assertEqual(self.stage.approved_count, 1)
        self.assertTrue(self.stage.is_complete)
        self.assertTrue(self.workflow.is_complete)

    def test_rejects_cancelled_workflow(self):
        self.workflow.is_cancelled = True
        self.workflow.save(update_fields=["is_cancelled"])

        with self.assertRaises(ValueError):
            record_decision(self.department_request, self.approver, approve=True)

        self.stage.refresh_from_db()
        self.assertEqual(self.stage.approved_count, 0)
