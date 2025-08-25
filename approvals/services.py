from django.db import transaction
from django.db.models import Q
from django.contrib.auth.models import User
from django.utils import timezone

from procurement.services import create_pos_from_recommended

from .models import (
    ApprovalPolicy, PRApprovalWorkflow, PRApprovalStageInstance, PRApprovalDecision
)

from django.conf import settings
from django.urls import reverse  # if you ever serve a backend link
from core.emails import send_plain_email


SYSTEM_USERNAME = "system"  # choose any reserved username


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
    policy = pick_policy_for_request(pr)
    if not policy or not policy.stages.exists():
        raise ValueError("No applicable approval policy/stages configured.")

    stages_qs = policy.stages.all().order_by("order")

    wf = PRApprovalWorkflow.objects.create(
        purchase_request=pr,
        policy=policy,
        current_stage_order=1,
        snapshot={
            "policy": {"id": policy.id, "name": policy.name},
            "stages": [
                {
                    "order": s.order,
                    "name": s.name,
                    "required_approvals": s.required_approvals,
                    "users": list(s.approver_users.values_list("id", flat=True)),
                    "groups": list(s.approver_groups.values_list("id", flat=True)),
                }
                for s in stages_qs
            ],
        },
    )

    # Create stage instances
    for s in stages_qs:
        u_ids = list(s.approver_users.values_list("id", flat=True))
        g_ids = list(s.approver_groups.values_list("id", flat=True))
        u_ids += _resolve_group_user_ids(g_ids)
        u_ids = sorted(set(u_ids))  # dedupe

        PRApprovalStageInstance.objects.create(
            workflow=wf,
            order=s.order,
            name=s.name,
            required_approvals=s.required_approvals,
            approver_user_ids=u_ids,
            approver_group_ids=g_ids,
        )

    _auto_bypass_self_approver(wf, pr.requestor)  # same as before
    _email_approvers_for_current_stage(wf, reason="Talep gönderildi")

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
            _email_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
            # TODO: notify next_stage approvers
        else:
            wf.is_complete = True
            wf.save(update_fields=["is_complete"])
            pr.status = "approved"
            pr.save(update_fields=["status"])
            created_pos = create_pos_from_recommended(pr)
            _email_requestor_on_final(pr, status_str="Onaylandı", comment="")
            # TODO: trigger post-approval handoff (e.g., enable pro-forma upload)



def _get_or_create_system_user():
    user, _ = User.objects.get_or_create(
        username=SYSTEM_USERNAME,
        defaults={"first_name": "System", "last_name": "User", "is_active": True},
    )
    return user


def _auto_bypass_self_approver(workflow: PRApprovalWorkflow, requestor: User) -> None:
    """
    - If a stage's approver list is exactly [requestor.id], mark that stage complete
      and create a synthetic 'approve' decision by SYSTEM user.
    - If a stage contains requestor among others, remove requestor from approvers and
      clamp required_approvals to the new approver count.
    - Repeat while we keep auto-completing stages (in case multiple early stages are self-only).
    """
    sys_user = _get_or_create_system_user()

    changed_wf = False
    # Keep advancing while we auto-complete stages
    while True:
        # find current stage
        stage = workflow.stage_instances.filter(
            order=workflow.current_stage_order
        ).first()
        if not stage or stage.is_complete or stage.is_rejected:
            break

        approvers = list(stage.approver_user_ids or [])
        # CASE A: only approver is the requestor -> auto-complete
        if len(approvers) == 1 and approvers[0] == requestor.id:
            # mark decision + complete
            PRApprovalDecision.objects.create(
                stage_instance=stage,
                approver=sys_user,
                decision="approve",   # keep your existing enum; 'approve' is safest
                comment="Auto-bypass: requestor is the sole approver for this stage.",
                decided_at=timezone.now(),
            )
            stage.approved_count = stage.required_approvals
            stage.is_complete = True
            stage.save(update_fields=["approved_count", "is_complete"])

            # advance workflow
            workflow.current_stage_order += 1
            changed_wf = True
            # loop again to check next stage (maybe also self-only)
            continue

        # CASE B: requestor is in the approver list with others -> remove them
        if requestor.id in approvers:
            approvers = [uid for uid in approvers if uid != requestor.id]
            stage.approver_user_ids = approvers
            # clamp required approvals to be <= available approvers
            if stage.required_approvals > len(approvers):
                stage.required_approvals = max(len(approvers), 0)
            stage.save(update_fields=["approver_user_ids", "required_approvals"])
            # do NOT advance; the stage still needs action from remaining approvers
        break

    # If we advanced past the last stage, finish workflow and PR
    last_order = workflow.stage_instances.order_by("-order").values_list("order", flat=True).first() or 0
    if workflow.current_stage_order > last_order:
        workflow.is_complete = True
        workflow.save(update_fields=["is_complete", "current_stage_order"])
        # also flip PR status to approved (mirror your existing finalize logic)
        pr = workflow.purchase_request
        pr.status = "approved"
        pr.save(update_fields=["status"])
        _email_requestor_on_final(pr, status_str="Onaylandı", comment="(Otomatik geçiş)")
    elif changed_wf:
        workflow.save(update_fields=["current_stage_order"])


def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)

def _approver_emails_for_stage(stage: PRApprovalStageInstance):
    qs = _users_from_ids(stage.approver_user_ids or [])
    return list(qs.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True))

def _pr_title(pr):
    # adjust if you have a title field; fall back gracefully
    return getattr(pr, "title", f"PR-{pr.id}")

def _pr_frontend_url(pr):
    # change to your real frontend route
    return f"https://ofis.gemcore.com.tr/procurement/purchase-requests/pending/?talep={pr.request_number}"

def _email_approvers_for_current_stage(workflow: PRApprovalWorkflow, reason: str = "pending"):
    """
    Sends an email to all approvers of the CURRENT stage of this workflow.
    No-op if workflow finished/rejected or stage has no approvers.
    """
    if workflow.is_complete or workflow.is_rejected:
        return

    stage = workflow.stage_instances.filter(order=workflow.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return

    pr = workflow.purchase_request
    to_list = _approver_emails_for_stage(stage)
    if not to_list:
        return

    subject = f"[Onay Gerekli] Satınalma Talebi #{pr.id} – {_pr_title(pr)}"
    body = (
        f"Merhaba,\n\n"
        f"Satınalma talebi (#{pr.id} – {_pr_title(pr)}) için onayınız bekleniyor.\n"
        f"Aşama: {stage.name} (Gerekli onay sayısı: {stage.required_approvals})\n"
        f"Öncelik: {getattr(pr, 'priority', '—')}\n"
        f"Talep Eden: {getattr(pr.requestor, 'get_full_name', lambda: pr.requestor.username)() if getattr(pr, 'requestor', None) else '—'}\n\n"
        f"İncelemek için: {_pr_frontend_url(pr)}\n\n"
        f"Not: Bu bildirim nedeni: {reason}."
    )
    send_plain_email(subject, body, to_list)

def _email_requestor_on_final(pr, status_str: str, comment: str = ""):
    if not getattr(pr, "requestor", None):
        return
    to = [pr.requestor.email] if getattr(pr.requestor, "email", "") else []
    if not to:
        return
    subject = f"[Satınalma Talebi {status_str}] PR #{pr.id} – {_pr_title(pr)}"
    body = (
        f"Merhaba,\n\n"
        f"Satınalma talebiniz (#{pr.id} – {_pr_title(pr)}) {status_str.lower()}.\n"
        f"{('Not: ' + comment) if comment else ''}\n\n"
        f"Detay: {_pr_frontend_url(pr)}"
    )
    send_plain_email(subject, body, to)