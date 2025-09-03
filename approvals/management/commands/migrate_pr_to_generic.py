from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.contenttypes.models import ContentType

from approvals.models import ApprovalWorkflow, ApprovalStageInstance, ApprovalDecision
from procurement.models import PurchaseRequest


# class Command(BaseCommand):
#     help = "Copy PRApproval* rows into generic Approval* tables (idempotent, safe)."

#     @transaction.atomic
#     def handle(self, *args, **opts):
#         ct_pr = ContentType.objects.get_for_model(PurchaseRequest)
#         migrated = 0

#         for legacy_wf in PRApprovalWorkflow.objects.all().select_related("purchase_request", "policy"):
#             pr = legacy_wf.purchase_request

#             # Skip if already migrated
#             if ApprovalWorkflow.objects.filter(content_type=ct_pr, object_id=pr.id).exists():
#                 self.stdout.write(self.style.WARNING(f"PR {pr.id} already migrated"))
#                 continue

#             # Create generic workflow
#             gen_wf = ApprovalWorkflow.objects.create(
#                 content_type=ct_pr,
#                 object_id=pr.id,
#                 policy=legacy_wf.policy,
#                 current_stage_order=legacy_wf.current_stage_order,
#                 is_complete=legacy_wf.is_complete,
#                 is_rejected=legacy_wf.is_rejected,
#                 is_cancelled=legacy_wf.is_cancelled,
#                 snapshot=legacy_wf.snapshot or {},
#             )

#             # Copy stage instances
#             id_map = {}
#             for lsi in PRApprovalStageInstance.objects.filter(workflow=legacy_wf):
#                 gsi = ApprovalStageInstance.objects.create(
#                     workflow=gen_wf,
#                     order=lsi.order,
#                     name=lsi.name,
#                     required_approvals=lsi.required_approvals,
#                     approver_user_ids=lsi.approver_user_ids,
#                     approver_group_ids=lsi.approver_group_ids,
#                     approved_count=lsi.approved_count,
#                     is_complete=lsi.is_complete,
#                     is_rejected=lsi.is_rejected,
#                 )
#                 id_map[lsi.id] = gsi

#             # Copy decisions
#             for ld in PRApprovalDecision.objects.filter(stage_instance__workflow=legacy_wf):
#                 ApprovalDecision.objects.create(
#                     stage_instance=id_map[ld.stage_instance_id],
#                     approver=ld.approver,
#                     decision=ld.decision,
#                     comment=ld.comment,
#                     decided_at=ld.decided_at,
#                 )

#             migrated += 1
#             self.stdout.write(self.style.SUCCESS(f"Migrated PR {pr.id} → gen WF {gen_wf.id}"))

#         self.stdout.write(self.style.SUCCESS(f"Done. Migrated {migrated} workflows."))
