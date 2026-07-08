from django.contrib.auth.models import User
from django.test import TestCase

from .models import ApprovalDecision, ApprovalPolicy, ApprovalStage
from .services import create_workflow, record_decision


class RecordDecisionPermissionTests(TestCase):
    def setUp(self):
        self.subject = User.objects.create_user(username='subject')
        self.approver = User.objects.create_user(username='approver')
        self.outsider = User.objects.create_user(username='outsider')
        self.superuser = User.objects.create_superuser(
            username='superuser',
            email='superuser@example.com',
            password='password',
        )
        self.policy = ApprovalPolicy.objects.create(
            name='Test approval policy',
            subject_type='test_subject',
        )
        self.policy_stage = ApprovalStage.objects.create(
            policy=self.policy,
            order=1,
            name='Manager approval',
            required_approvals=1,
        )
        self.policy_stage.approver_users.add(self.approver)

    def create_subject_workflow(self):
        return create_workflow(self.subject, self.policy)

    def test_non_approver_cannot_record_decision(self):
        wf = self.create_subject_workflow()

        with self.assertRaises(PermissionError):
            record_decision(self.subject, self.outsider, approve=True)

        wf.refresh_from_db()
        self.assertFalse(wf.is_complete)
        self.assertEqual(ApprovalDecision.objects.count(), 0)

    def test_stage_approver_can_record_decision(self):
        self.create_subject_workflow()

        wf, stage, outcome = record_decision(self.subject, self.approver, approve=True)

        self.assertEqual(outcome, 'completed')
        self.assertTrue(wf.is_complete)
        self.assertTrue(stage.is_complete)
        self.assertEqual(ApprovalDecision.objects.count(), 1)

    def test_superuser_can_override_stage_approver_membership(self):
        self.create_subject_workflow()

        wf, stage, outcome = record_decision(self.subject, self.superuser, approve=True)

        self.assertEqual(outcome, 'completed')
        self.assertTrue(wf.is_complete)
        self.assertTrue(stage.is_complete)
        self.assertEqual(ApprovalDecision.objects.count(), 1)

    def test_cancelled_workflow_cannot_be_decided(self):
        wf = self.create_subject_workflow()
        wf.is_cancelled = True
        wf.save(update_fields=['is_cancelled'])

        with self.assertRaisesMessage(ValueError, 'Workflow cancelled.'):
            record_decision(self.subject, self.approver, approve=True)

        wf.refresh_from_db()
        self.assertFalse(wf.is_complete)
        self.assertEqual(ApprovalDecision.objects.count(), 0)
