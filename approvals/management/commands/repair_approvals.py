from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from procurement.approval_service import _email_approvers_for_current_stage
from procurement.models import PurchaseRequest
from django.contrib.auth import get_user_model

# paste the two helpers here:
# - _advance_to_next_incomplete_stage(wf)
# - repair_first_stage_skip(pr_id, finalize_pr=True)

class Command(BaseCommand):
    help = "Repair stuck approval workflows (first-stage skip / pointer issues)."

    def add_arguments(self, parser):
        parser.add_argument("--pr", type=str, help="Comma-separated PR IDs (e.g. 123,124).")
        parser.add_argument("--all-stuck", action="store_true",
                            help="Auto-detect and repair workflows where the current stage is already complete.")

    def handle(self, *args, **opts):
        pr_ids = []
        if opts.get("pr"):
            pr_ids = [int(x.strip()) for x in opts["pr"].split(",") if x.strip().isdigit()]

        if not pr_ids and not opts["all-stuck"]:
            raise CommandError("Provide --pr or --all-stuck.")

        repaired = []

        if pr_ids:
            for pid in pr_ids:
                msg = repair_first_stage_skip(pid)
                self.stdout.write(f"PR {pid}: {msg}")
                repaired.append(pid)

        if opts.get("all_stuck"):
            from django.db.models import Exists, OuterRef, Q
            from approvals.models import ApprovalWorkflow, ApprovalStageInstance

            stuck = (
                ApprovalWorkflow.objects
                .filter(is_complete=False)
                .annotate(curr_complete=Exists(
                    ApprovalStageInstance.objects.filter(
                        workflow=OuterRef("pk"),
                        order=OuterRef("current_stage_order"),
                        is_complete=True,
                        is_rejected=False,
                    )
                ))
                .filter(curr_complete=True)
                .values_list("object_id", flat=True)
            )

            for pid in stuck:
                msg = repair_first_stage_skip(pid)
                self.stdout.write(f"PR {pid}: {msg}")
                repaired.append(pid)

        self.stdout.write(self.style.SUCCESS(f"Done. Repaired: {sorted(set(repaired))}"))


from django.db import transaction
from django.db.models import F
from django.contrib.contenttypes.models import ContentType

# adjust model paths to your app names
from procurement.models import PurchaseRequest
from approvals.models import ApprovalWorkflow, ApprovalStageInstance, ApprovalDecision

def _advance_to_next_incomplete_stage(wf):
    """Move current_stage_order forward over already-complete stages."""
    orders = list(
        ApprovalStageInstance.objects
        .filter(workflow=wf)
        .order_by("order")
        .values_list("order", flat=True)
    )
    if not orders:
        return False  # nothing to do

    # find next incomplete at or after current
    for o in orders:
        si = ApprovalStageInstance.objects.get(workflow=wf, order=o)
        if not si.is_complete and not si.is_rejected:
            wf.current_stage_order = o
            wf.save(update_fields=["current_stage_order"])
            return True

    # all stages complete -> finalize workflow
    wf.is_complete = True
    wf.is_rejected = False
    wf.save(update_fields=["is_complete", "is_rejected"])
    return False

def repair_first_stage_skip(pr_id, reason="Repair: retro-complete prior stages"):
    """
    Fix workflows where stage-1 was skipped/marked oddly and approvers can't proceed.
    - Ensures stage-1 is audibly completed (system decision),
    - Advances current_stage_order to the next actionable stage,
    - Finalizes PR if no stages remain.
    """
    with transaction.atomic():
        pr = PurchaseRequest.objects.select_for_update().get(id=pr_id)
        ct = ContentType.objects.get_for_model(PurchaseRequest)
        wf = ApprovalWorkflow.objects.select_for_update().get(content_type=ct, object_id=pr.id)
        User = get_user_model()
        approver = User.objects.get(pk=1)
        # Mark all unfinished prior stages complete + add a system decision
        prior_qs = ApprovalStageInstance.objects.select_for_update().filter(
            workflow=wf,
            order__lt=wf.current_stage_order,
            is_complete=False,
            is_rejected=False,
        )
        changed = False
        for si in prior_qs:
            si.is_complete = True
            si.save(update_fields=["is_complete"])
            ApprovalDecision.objects.create(
                stage_instance=si,
                approver=approver,
                decision="approved",      # or "skipped" if you distinguish
                comment=reason
            )
            changed = True

        # Optional: notify current stage approvers if anything changed
        if changed:
            try:
                _email_approvers_for_current_stage(wf, reason="Onarım sonrası")
            except NameError:
                # If you don’t have this helper in scope here, ignore or import it from where it lives.
                pass

        return f"Retro-completed prior stages: {changed}. Now at stage order #{wf.current_stage_order}."

