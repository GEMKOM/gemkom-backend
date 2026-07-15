from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from approvals.models import (
    ApprovalPolicy,
    ApprovalStage,
    ApprovalStageInstance,
    ApprovalWorkflow,
)
from procurement.approval_service import decide, submit_purchase_request
from procurement.models import PurchaseRequest, PurchaseRequestDraft
from procurement.services import cancel_purchase_request, revise_purchase_request


class PurchaseRequestCancellationConcurrencyTests(TestCase):
    def setUp(self):
        self.requestor = User.objects.create_user(
            username="requestor",
            password="test",
        )
        self.approver = User.objects.create_user(
            username="approver",
            password="test",
        )
        self.policy = ApprovalPolicy.objects.create(
            name="Purchase request test policy",
            subject_type="purchase_request",
        )
        self.policy_stage = ApprovalStage.objects.create(
            policy=self.policy,
            order=1,
            name="Approval",
            required_approvals=1,
        )
        self.policy_stage.approver_users.add(self.approver)

    def _purchase_request(self):
        return PurchaseRequest.objects.create(
            request_number=f"PR-TEST-{PurchaseRequest.objects.count() + 1}",
            title="Test request",
            requestor=self.requestor,
            status="submitted",
        )

    def _workflow(self, pr):
        workflow = ApprovalWorkflow.objects.create(
            content_type=ContentType.objects.get_for_model(PurchaseRequest),
            object_id=pr.pk,
            policy=self.policy,
        )
        ApprovalStageInstance.objects.create(
            workflow=workflow,
            order=1,
            name="Approval",
            required_approvals=1,
            approver_user_ids=[self.approver.pk],
        )
        return workflow

    def test_cancel_closes_generic_approval_workflow(self):
        pr = self._purchase_request()
        workflow = self._workflow(pr)

        cancel_purchase_request(pr, self.requestor, reason="No longer needed")

        pr.refresh_from_db()
        workflow.refresh_from_db()
        self.assertEqual(pr.status, "cancelled")
        self.assertTrue(workflow.is_cancelled)

    def test_revise_rechecks_status_from_locked_row(self):
        stale_pr = self._purchase_request()
        PurchaseRequest.objects.filter(pk=stale_pr.pk).update(status="cancelled")

        with self.assertRaisesMessage(
            ValidationError,
            "Only submitted, approved, or rejected purchase requests can be revised.",
        ):
            revise_purchase_request(stale_pr, self.requestor)

        self.assertFalse(PurchaseRequestDraft.objects.exists())

    def test_decide_cannot_resurrect_cancelled_request_from_stale_instance(self):
        stale_pr = self._purchase_request()
        workflow = self._workflow(stale_pr)
        PurchaseRequest.objects.filter(pk=stale_pr.pk).update(status="cancelled")

        with self.assertRaisesMessage(
            ValidationError,
            "Only submitted purchase requests can be approved or rejected.",
        ):
            decide(stale_pr, self.approver, approve=True)

        stale_pr.refresh_from_db()
        workflow.refresh_from_db()
        self.assertEqual(stale_pr.status, "cancelled")
        self.assertFalse(workflow.is_complete)
        self.assertFalse(workflow.stage_instances.get().decisions.exists())

    def test_submit_rechecks_cancelled_status_from_locked_row(self):
        stale_pr = self._purchase_request()
        PurchaseRequest.objects.filter(pk=stale_pr.pk).update(status="cancelled")

        with self.assertRaisesMessage(
            ValidationError,
            "Only submitted purchase requests can enter approval.",
        ):
            submit_purchase_request(stale_pr, self.requestor)

        self.assertFalse(stale_pr.approvals.exists())
