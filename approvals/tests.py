from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from .models import ApprovalPolicy, ApprovalStageInstance, ApprovalWorkflow, ApprovalDecision
from .services import record_decision


class RecordDecisionAuthorizationTests(TestCase):
    def setUp(self):
        self.subject = User.objects.create_user(username="requester")
        self.approver = User.objects.create_user(username="approver")
        self.other_user = User.objects.create_user(username="other")
        self.admin_user = User.objects.create_user(username="admin", is_staff=True)
        self.policy = ApprovalPolicy.objects.create(
            name="Sales approval auth test",
            subject_type="sales_offer",
        )

    def _create_workflow(self, *, approver_ids=None, is_cancelled=False):
        workflow = ApprovalWorkflow.objects.create(
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.subject.id,
            policy=self.policy,
            is_cancelled=is_cancelled,
        )
        ApprovalStageInstance.objects.create(
            workflow=workflow,
            order=1,
            name="Stage 1",
            required_approvals=1,
            approver_user_ids=approver_ids if approver_ids is not None else [self.approver.id],
        )
        return workflow

    def test_record_decision_rejects_non_stage_approver(self):
        workflow = self._create_workflow()

        with self.assertRaisesMessage(ValueError, "You are not an approver for this stage."):
            record_decision(self.subject, self.other_user, approve=True)

        stage = workflow.stage_instances.get(order=1)
        self.assertEqual(stage.approved_count, 0)
        self.assertFalse(stage.is_complete)
        self.assertFalse(ApprovalDecision.objects.filter(stage_instance=stage).exists())

    def test_record_decision_allows_assigned_stage_approver(self):
        workflow = self._create_workflow()

        _, stage, outcome = record_decision(self.subject, self.approver, approve=True)

        workflow.refresh_from_db()
        stage.refresh_from_db()
        self.assertEqual(outcome, "completed")
        self.assertTrue(workflow.is_complete)
        self.assertTrue(stage.is_complete)
        self.assertEqual(stage.approved_count, 1)

    def test_record_decision_preserves_admin_override(self):
        workflow = self._create_workflow()

        _, stage, outcome = record_decision(self.subject, self.admin_user, approve=True)

        workflow.refresh_from_db()
        stage.refresh_from_db()
        self.assertEqual(outcome, "completed")
        self.assertTrue(workflow.is_complete)
        self.assertTrue(stage.is_complete)

    def test_record_decision_rejects_cancelled_workflow(self):
        workflow = self._create_workflow(is_cancelled=True)

        with self.assertRaisesMessage(ValueError, "Workflow already finished."):
            record_decision(self.subject, self.approver, approve=True)

        stage = workflow.stage_instances.get(order=1)
        self.assertFalse(stage.is_complete)
        self.assertFalse(ApprovalDecision.objects.filter(stage_instance=stage).exists())
