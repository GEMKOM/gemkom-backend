from django.db import transaction
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone

from .models import (
    ApprovalPolicy, PRApprovalWorkflow, PRApprovalStageInstance, PRApprovalDecision
)

def pick_policy_for_request(pr):
    qs = ApprovalPolicy.objects.filter(is_active=True)
    if pr.total_amount_eur is not None:
        qs = qs.filter(
            Q(min_amount_eur__isnull=True) | Q(min_amount_eur__lte=pr.total_amount_eur),
            Q(max_amount_eur__isnull=True) | Q(max_amount_eur__gte=pr.total_amount_eur),
        )
    if pr.priority:
        qs = qs.filter(Q(priority_in=[]) | Q(priority_in__contains=[pr.priority]))
    return qs.order_by("selection_priority").first()

def _resolve_group_user_ids(group_ids):
    return list(
        User.objects.filter(groups__id__in=group_ids, is_active=True)
        .values_list("id", flat=True).distinct()
    )

def user_can_approve_stage(user, pr, stage: PRApprovalStageInstance):
    if pr.requestor_id == user.id:
        return False
    return (user.id in stage.approver_user_ids) and (not stage.is_complete) and (not stage.is_rejected)

@transaction.atomic
def submit_purchase_request(pr, by_user):
    if pr.status != "draft":
        raise ValueError("Only draft requests can be submitted.")
    policy = pick_policy_for_request(pr)
    if not policy or not policy.stages.exists():
        raise ValueError("No applicable approval policy/stages configured.")

    wf = PRApprovalWorkflow.objects.create(
        purchase_request=pr,
        policy=policy,
        current_stage_order=1,
        snapshot={
            "policy": {"id": policy.id, "name": policy.name},
            "stages": [
                {
                    "order": s.order, "name": s.name,
                    "required_approvals": s.required_approvals,
                    "users": list(s.approver_users.values_list("id", flat=True)),
                    "groups": list(s.approver_groups.values_list("id", flat=True)),
                }
                for s in policy.stages.all().order_by("order")
            ],
        },
    )

    for s in policy.stages.all().order_by("order"):
        u_ids = list(s.approver_users.values_list("id", flat=True))
        g_ids = list(s.approver_groups.values_list("id", flat=True))
        u_ids += _resolve_group_user_ids(g_ids)
        u_ids = sorted(set(u_ids))

        PRApprovalStageInstance.objects.create(
            workflow=wf,
            order=s.order,
            name=s.name,
            required_approvals=s.required_approvals,
            approver_user_ids=u_ids,
            approver_group_ids=g_ids,
        )

    pr.status = "submitted"
    pr.submitted_at = timezone.now()
    pr.save(update_fields=["status", "submitted_at"])

    # TODO: notify stage-1 approvers here
    return wf

@transaction.atomic
def decide(pr, user, approve: bool, comment: str = ""):
    wf = PRApprovalWorkflow.objects.select_for_update().get(purchase_request=pr)
    if wf.is_complete or wf.is_rejected:
        raise ValueError("Workflow already finished.")

    stage = PRApprovalStageInstance.objects.select_for_update().get(
        workflow=wf, order=wf.current_stage_order
    )
    if not user_can_approve_stage(user, pr, stage):
        raise PermissionError("You are not an approver for the current stage.")

    if PRApprovalDecision.objects.filter(stage_instance=stage, approver=user).exists():
        raise ValueError("You already decided on this stage.")

    PRApprovalDecision.objects.create(
        stage_instance=stage, approver=user,
        decision="approve" if approve else "reject",
        comment=comment,
    )

    if not approve:
        stage.is_rejected = True
        stage.save(update_fields=["is_rejected"])
        wf.is_rejected = True
        wf.save(update_fields=["is_rejected"])
        pr.status = "rejected"
        pr.save(update_fields=["status"])
        return

    # approval path
    stage.approved_count += 1
    if stage.approved_count >= stage.required_approvals:
        stage.is_complete = True
    stage.save(update_fields=["approved_count", "is_complete"])

    if stage.is_complete:
        next_stage = PRApprovalStageInstance.objects.filter(
            workflow=wf, order__gt=stage.order
        ).order_by("order").first()
        if next_stage:
            wf.current_stage_order = next_stage.order
            wf.save(update_fields=["current_stage_order"])
            # TODO: notify next_stage approvers
        else:
            wf.is_complete = True
            wf.save(update_fields=["is_complete"])
            pr.status = "approved"
            pr.save(update_fields=["status"])
            # TODO: trigger post-approval handoff (e.g., enable pro-forma upload)
