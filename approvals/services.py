# approvals/services_core.py
from __future__ import annotations
from typing import Callable, Optional, Tuple

from django.db import transaction
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from .models import (
    ApprovalWorkflow,
    ApprovalStageInstance,
    ApprovalDecision,
)


def _notify_subject(wf: ApprovalWorkflow, event: str, payload: Optional[dict] = None):
    """Call subject.handle_approval_event(...) if it exists."""
    subject = wf.subject
    handler = getattr(subject, "handle_approval_event", None)
    if callable(handler):
        handler(workflow=wf, event=event, payload=payload or {})

# --------- Small generic utilities ---------
def resolve_group_user_ids(group_ids) -> list[int]:
    """Expand Django Group ids to active user ids (deduped)."""
    if not group_ids:
        return []
    return list(
        User.objects.filter(groups__id__in=group_ids, is_active=True)
        .values_list("id", flat=True)
        .distinct()
    )


def get_workflow(subject) -> ApprovalWorkflow:
    """Fetch the workflow for any subject object (by content type + id)."""
    ct = ContentType.objects.get_for_model(type(subject))
    return ApprovalWorkflow.objects.get(content_type=ct, object_id=subject.id)


# --------- Creation ---------
def create_workflow(
    subject,
    policy,
    snapshot: Optional[dict] = None,
    *,
    approver_user_ids_builder: Optional[
        Callable[[object, object], tuple[list[int], list[int]]]
    ] = None,
) -> ApprovalWorkflow:
    """
    Create a workflow for any subject using the given policy.

    - approver_user_ids_builder(stage, subject) -> (user_ids, group_ids)
      If not provided, uses the users/groups directly from the policy stage
      and DOES NOT expand groups (domain may expand later if desired).
    """
    ct = ContentType.objects.get_for_model(type(subject))
    wf = ApprovalWorkflow.objects.create(
        content_type=ct,
        object_id=subject.id,
        policy=policy,
        current_stage_order=1,
        snapshot=snapshot or {},
    )

    for s in policy.stages.all().order_by("order"):
        if approver_user_ids_builder:
            u_ids, g_ids = approver_user_ids_builder(s, subject)
        else:
            u_ids = list(s.approver_users.values_list("id", flat=True))
            g_ids = list(s.approver_groups.values_list("id", flat=True))

        ApprovalStageInstance.objects.create(
            workflow=wf,
            order=s.order,
            name=s.name,
            required_approvals=s.required_approvals,
            approver_user_ids=list(dict.fromkeys(u_ids)),  # dedupe, keep order
            approver_group_ids=g_ids,
        )
    return wf


# --------- Decision & progression ---------
@transaction.atomic
def record_decision(subject, user, approve: bool, comment: str = "") -> tuple[ApprovalWorkflow, ApprovalStageInstance, str]:
    """
    Approve/Reject on the subject's CURRENT stage.
    Returns: (workflow, current_or_next_stage, outcome)
      outcome ∈ {"rejected", "moved", "completed", "pending"}
    """
    wf = get_workflow(subject)
    if wf.is_complete or wf.is_rejected:
        raise ValueError("Workflow already finished.")

    stage = ApprovalStageInstance.objects.select_for_update(nowait=True).get(
        workflow=wf, order=wf.current_stage_order
    )
    if stage.is_complete or stage.is_rejected:
        next_stage = wf.stage_instances.filter(order__gt=stage.order).order_by("order").first()
        if next_stage:
            return wf, next_stage, "moved"
        return wf, stage, "completed" if wf.is_complete else "pending"

    # idempotency
    if ApprovalDecision.objects.filter(stage_instance=stage, approver=user).exists():
        raise ValueError("You already decided on this stage.")

    ApprovalDecision.objects.create(
        stage_instance=stage,
        approver=user,
        decision="approve" if approve else "reject",
        comment=comment,
    )

    if not approve:
        stage.is_rejected = True
        stage.save(update_fields=["is_rejected"])
        wf.is_rejected = True
        wf.save(update_fields=["is_rejected"])
        _notify_subject(wf, "rejected", {"stage_order": stage.order, "comment": comment})
        return wf, stage, "rejected"

    # approval path
    stage.approved_count += 1
    if stage.approved_count >= stage.required_approvals:
        stage.is_complete = True
    stage.save(update_fields=["approved_count", "is_complete"])

    if stage.is_complete:
        next_stage = wf.stage_instances.filter(order__gt=stage.order).order_by("order").first()
        if next_stage:
            wf.current_stage_order = next_stage.order
            wf.save(update_fields=["current_stage_order"])
            _notify_subject(wf, "stage_advanced", {"from_stage_order": stage.order, "to_stage_order": next_stage.order})
            return wf, next_stage, "moved"
        else:
            wf.is_complete = True
            wf.save(update_fields=["is_complete"])
            _notify_subject(wf, "approved", {"last_stage_order": stage.order})
            return wf, stage, "completed"

    return wf, stage, "pending"


# --------- Self-approver auto-bypass (generic) ---------
def auto_bypass_self_approver(wf: ApprovalWorkflow, requestor_user_id: int) -> tuple[bool, bool]:
    """
    If the current stage's only approver is the requestor, auto-approve and advance.
    If the requestor is among multiple approvers, remove them and clamp quorum.
    Returns: (changed_workflow, finished)
    """
    changed_wf = False
    while True:
        stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not stage or stage.is_complete or stage.is_rejected:
            break

        approvers = list(stage.approver_user_ids or [])

        # A) only approver is the requestor -> auto-complete
        if len(approvers) == 1 and approvers[0] == requestor_user_id:
            # create a synthetic decision by a system user? keep engine neutral:
            ApprovalDecision.objects.create(
                stage_instance=stage,
                approver=User.objects.get_or_create(
                    username="system",
                    defaults={"first_name": "System", "last_name": "User", "is_active": True},
                )[0],
                decision="approve",
                comment="Oto-geçiş: Talep eden kişi onaylama yetkisine sahip.",
            )
            stage.approved_count = stage.required_approvals
            stage.is_complete = True
            stage.save(update_fields=["approved_count", "is_complete"])
            wf.current_stage_order += 1
            changed_wf = True
            continue

        # B) requestor among others -> remove them and clamp quorum
        if requestor_user_id in approvers:
            approvers = [uid for uid in approvers if uid != requestor_user_id]
            stage.approver_user_ids = approvers
            if stage.required_approvals > len(approvers):
                stage.required_approvals = max(len(approvers), 0)
            stage.save(update_fields=["approver_user_ids", "required_approvals"])
        break

    last_order = wf.stage_instances.order_by("-order").values_list("order", flat=True).first() or 0
    finished = wf.current_stage_order > last_order
    if finished:
        wf.is_complete = True
        wf.save(update_fields=["is_complete", "current_stage_order"])
        _notify_subject(wf, "approved", {"auto_bypass": True, "reason": "requestor sole approver"})
    elif changed_wf:
        wf.save(update_fields=["current_stage_order"])
        _notify_subject(wf, "stage_advanced", {"auto_bypass": True, "to_stage_order": wf.current_stage_order})
    return changed_wf, finished
