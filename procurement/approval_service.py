# procurement/approval_service.py
from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import User

from approvals.services import (
    create_workflow,
    get_workflow,
    record_decision,
    auto_bypass_self_approver,
    resolve_group_user_ids,
)
from approvals.models import ApprovalPolicy
from approvals.models import ApprovalStageInstance, ApprovalWorkflow, ApprovalDecision

from .models import PurchaseRequest
from procurement.services import create_pos_from_recommended
from django.db.models import Max, Q

from notifications.service import notify, bulk_notify, render_notification
from notifications.models import Notification
from users.helpers import users_in_team


SYSTEM_USERNAME = "system"


# --------- Policy selection (PR-specific) ---------
def pick_policy_for_purchase_request(pr: PurchaseRequest):
    qs = ApprovalPolicy.objects.filter(
        is_active=True,
        is_rolling_mill=pr.is_rolling_mill,
    )
    if pr.total_amount_eur is not None:
        qs = qs.filter(
            Q(min_amount_eur__isnull=True) | Q(min_amount_eur__lte=pr.total_amount_eur),
            Q(max_amount_eur__isnull=True) | Q(max_amount_eur__gte=pr.total_amount_eur),
        )
    if getattr(pr, "priority", None):
        qs = qs.filter(Q(priority_in=[]) | Q(priority_in__contains=[pr.priority]))

    return qs.order_by("selection_priority").first()


# --------- Helpers ---------
def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)

def _pr_title(pr: PurchaseRequest):
    return getattr(pr, "title", f"PR-{pr.id}")

def _pr_frontend_url(pr: PurchaseRequest):
    return f"https://ofis.gemcore.com.tr/procurement/purchase-requests/pending/?talep={pr.request_number}"

def _po_frontend_url(po):
    return f"https://ofis.gemcore.com.tr/finance/purchase-orders/?order={po.id}"


def _notify_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    pr = PurchaseRequest.objects.get(id=wf.object_id)
    approvers = _users_from_ids(stage.approver_user_ids or [])
    if not approvers.exists():
        return
    ctx = {
        'pr_id':               pr.id,
        'pr_title':            _pr_title(pr),
        'stage_name':          stage.name,
        'required_approvals':  stage.required_approvals,
        'priority':            getattr(pr, 'priority', '—'),
        'requestor':           getattr(pr.requestor, 'get_full_name', lambda: pr.requestor.username)() if getattr(pr, 'requestor', None) else '—',
        'reason':              reason,
    }
    title, body, link = render_notification(Notification.PR_APPROVAL_REQUESTED, ctx)
    bulk_notify(
        users=approvers,
        notification_type=Notification.PR_APPROVAL_REQUESTED,
        title=title,
        body=body,
        link=link,
        source_type='purchase_request',
        source_id=pr.id,
    )


def _notify_requestor_on_final(pr: PurchaseRequest, status_str: str, comment: str = ""):
    if not getattr(pr, "requestor", None):
        return
    notification_type = Notification.PR_APPROVED if status_str == "Onaylandı" else Notification.PR_REJECTED
    ctx = {
        'pr_id':    pr.id,
        'pr_title': _pr_title(pr),
        'comment':  comment,
    }
    title, body, link = render_notification(notification_type, ctx)
    notify(
        user=pr.requestor,
        notification_type=notification_type,
        title=title,
        body=body,
        link=link,
        source_type='purchase_request',
        source_id=pr.id,
    )


def _notify_finance_pos_created(pr: PurchaseRequest, pos_list):
    if not pos_list:
        return
    finance_users = users_in_team("finance")
    if not finance_users.exists():
        return
    pr_title = getattr(pr, "title", f"PR-{pr.id}")
    lines = []
    for po in pos_list:
        supplier_name = getattr(getattr(po, "supplier", None), "name", "—")
        currency = getattr(po, "currency", "")
        total = getattr(po, "total_amount", "")
        try:
            status_display = po.get_status_display()
        except Exception:
            status_display = getattr(po, "status", "")
        lines.append(f"- PO #{po.id} | Tedarikçi: {supplier_name} | Tutar: {currency} {total} | Durum: {status_display}")
    ctx = {
        'pr_id':    pr.id,
        'pr_title': pr_title,
        'po_list':  "\n".join(lines),
    }
    title, body, link = render_notification(Notification.PR_PO_CREATED, ctx)
    bulk_notify(
        users=finance_users,
        notification_type=Notification.PR_PO_CREATED,
        title=title,
        body=body,
        link=link,
        source_type='purchase_request',
        source_id=pr.id,
    )


# --------- Submit PR (uses core engine) ---------
def submit_purchase_request(pr: PurchaseRequest, by_user):
    with transaction.atomic():
        policy = pick_policy_for_purchase_request(pr)
        if not policy or not policy.stages.exists():
            raise ValueError("No applicable approval policy/stages configured.")

        # Build a snapshot for audit/viewing
        stages_qs = policy.stages.all().order_by("order")
        snapshot = {
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
        }

        # Expand groups to users for actual approvers
        def _builder(stage, _subject):
            u_ids = list(stage.approver_users.values_list("id", flat=True))
            g_ids = list(stage.approver_groups.values_list("id", flat=True))
            u_ids += resolve_group_user_ids(g_ids)
            # dedupe, keep order
            seen = set()
            ordered = []
            for uid in u_ids:
                if uid not in seen:
                    seen.add(uid)
                    ordered.append(uid)
            return ordered, g_ids

        wf = create_workflow(pr, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

        moved = False
        finished = False
        # Auto-bypass if the requester is the sole approver for current stage(s)
        while True:
            changed, done = auto_bypass_self_approver(wf, pr.requestor_id)
            moved |= bool(changed)
            finished |= bool(done)
            if done or not changed:
                break
        if finished:
            pr.status = "approved"
            pr.save(update_fields=["status"])
            created_pos = create_pos_from_recommended(pr)

    # Notifications sent outside the transaction
    if finished:
        _notify_requestor_on_final(pr, status_str="Onaylandı", comment="(Otomatik geçiş)")
        return wf

    if moved:
        _notify_approvers_for_current_stage(wf, reason="Talep gönderildi")

    return wf


# --------- Decide on PR (uses core engine) ---------
def decide(pr: PurchaseRequest, user, approve: bool, comment: str = ""):
    # DB writes in a transaction; notifications run after commit.
    created_pos = []
    with transaction.atomic():
        wf, stage, outcome = record_decision(pr, user, approve, comment)

        if outcome == "rejected":
            pr.status = "rejected"
            pr.save(update_fields=["status"])

        elif outcome == "completed":
            pr.status = "approved"
            pr.save(update_fields=["status"])
            created_pos = create_pos_from_recommended(pr)

        elif outcome == "pending":
            return wf

    # Notifications sent outside the transaction
    if outcome == "moved":
        _notify_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
    elif outcome == "completed":
        _notify_requestor_on_final(pr, status_str="Onaylandı", comment="")
        _notify_finance_pos_created(pr, created_pos)
    elif outcome == "rejected":
        _notify_requestor_on_final(pr, status_str="Reddedildi", comment=comment)

    return wf


def _skip_current_stage(wf, reason: str = "Auto-skip", system_user=None):
    """
    Skips the *current* stage in a way that keeps your approval model consistent.
    Returns (changed: bool, finished: bool).
    """
    from approvals.models import ApprovalWorkflow, ApprovalDecision  # adjust import path if different

    with transaction.atomic():
        # Re-load & lock to avoid concurrent pointer moves
        wf = ApprovalWorkflow.objects.select_for_update().get(pk=wf.pk)

        # Already terminal?
        if wf.is_complete or wf.is_rejected or wf.is_cancelled:
            return False, wf.is_complete

        current_order = wf.current_stage_order
        if not current_order:
            return False, False

        # Your related_name is "stage_instances"
        qs = wf.stage_instances
        cur = qs.select_for_update().filter(order=current_order).first()
        if not cur:
            return False, False

        changed = False

        # If stage is still actionable, mark it as completed (skipped == approved quorum reached)
        if not cur.is_complete and not cur.is_rejected:
            cur.is_complete = True
            # Treat skip as meeting quorum
            cur.approved_count = cur.required_approvals or 1
            cur.save(update_fields=["is_complete", "approved_count"])
            changed = True

            # Optional audit trail: record a single system "approve" decision
            if system_user is not None:
                # Unique per (stage_instance, approver); safe to get_or_create
                ApprovalDecision.objects.get_or_create(
                    stage_instance=cur,
                    approver=system_user,
                    defaults={"decision": "approve", "comment": f"[{reason}]"}
                )

        # Find the next incomplete & not rejected stage
        next_stage = (
            qs.filter(order__gt=current_order, is_complete=False, is_rejected=False)
              .order_by("order")
              .first()
        )
        if next_stage:
            wf.current_stage_order = next_stage.order
            wf.save(update_fields=["current_stage_order"])
            return changed, False

        # No actionable stages remain → finish the workflow
        max_order = qs.aggregate(m=Max("order"))["m"] or current_order
        wf.is_complete = True
        wf.current_stage_order = max_order + 1  # sentinel beyond last to avoid re-processing
        wf.save(update_fields=["is_complete", "current_stage_order"])
        return True, True
