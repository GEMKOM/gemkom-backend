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
from core.emails import send_plain_email
from django.db.models import Max, Q


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


# --------- Helpers (PR-specific emails/urls) ---------
def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)

def _approver_emails_for_stage(stage: ApprovalStageInstance):
    qs = _users_from_ids(stage.approver_user_ids or [])
    return list(qs.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True))

def _pr_title(pr: PurchaseRequest):
    return getattr(pr, "title", f"PR-{pr.id}")

def _pr_frontend_url(pr: PurchaseRequest):
    return f"https://ofis.gemcore.com.tr/procurement/purchase-requests/pending/?talep={pr.request_number}"

def _po_frontend_url(po):
    return f"https://ofis.gemcore.com.tr/finance/purchase-orders/?order={po.id}"

def _email_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    pr = PurchaseRequest.objects.get(id=wf.object_id)
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

def _email_requestor_on_final(pr: PurchaseRequest, status_str: str, comment: str = ""):
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

def _finance_emails():
    return list(
        User.objects.filter(is_active=True, profile__team="finance")
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )

def _email_finance_pos_created(pr: PurchaseRequest, pos_list):
    if not pos_list:
        return
    to = _finance_emails()
    if not to:
        return
    pr_title = getattr(pr, "title", f"PR-{pr.id}")
    lines = []
    for po in pos_list:
        supplier_name = getattr(getattr(po, "supplier", None), "name", "—")
        currency = getattr(po, "currency", "")
        total = getattr(po, "total_amount", "")
        status = getattr(po, "status", "")
        po_url = _po_frontend_url(po)
        try:
            status = po.get_status_display()
        except Exception:
            pass
        lines.append(f"- PO #{po.id} | Tedarikçi: {supplier_name} | Tutar: {currency} {total} | Durum: {status} | URL: {po_url}")
    subject = f"[PO Oluşturuldu] PR #{pr.id} – {pr_title}"
    body = (
        f"Merhaba Finans,\n\n"
        f"Satınalma talebi (PR #{pr.id} – {pr_title}) onaylandı ve aşağıdaki satınalma siparişleri oluşturuldu:\n\n"
        + "\n".join(lines)
    )
    send_plain_email(subject, body, to)


# --------- Submit PR (uses core engine) ---------
@transaction.atomic
def submit_purchase_request(pr: PurchaseRequest, by_user):
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

    # -------- NEW: auto-skip first stage for external_workshops --------
    requester_team = getattr(getattr(pr, "requestor", None), "profile", None)
    requester_team = getattr(requester_team, "team", None)

    moved = False     # track if current stage changed at any point
    finished = False  # track if workflow ended

    if requester_team == "external_workshops":
        if (getattr(wf, "current_stage_order", 0) or 0) == 1:
            skipped, done = _skip_current_stage(wf, reason="Auto-skip for external_workshops")
            moved |= bool(skipped)
            finished |= bool(done)
            if finished:
                pr.status = "approved"
                pr.save(update_fields=["status"])
                created_pos = create_pos_from_recommended(pr)
                _email_requestor_on_final(pr, status_str="Onaylandı", comment="(Dış atölye: 1. aşama atlandı)")
                _email_finance_pos_created(pr, created_pos)
                return wf

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
        _email_requestor_on_final(pr, status_str="Onaylandı", comment="(Otomatik geçiş)")
        return wf

    if moved:
        _email_approvers_for_current_stage(wf, reason="Talep gönderildi")

    return wf


# --------- Decide on PR (uses core engine) ---------
@transaction.atomic
def decide(pr: PurchaseRequest, user, approve: bool, comment: str = ""):
    wf, stage, outcome = record_decision(pr, user, approve, comment)

    if outcome == "rejected":
        pr.status = "rejected"
        pr.save(update_fields=["status"])
        return wf

    if outcome == "moved":
        _email_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        pr.status = "approved"
        pr.save(update_fields=["status"])
        created_pos = create_pos_from_recommended(pr)
        _email_requestor_on_final(pr, status_str="Onaylandı", comment="")
        _email_finance_pos_created(pr, created_pos)
        return wf

    # "pending" → quorum not yet reached; no side effect
    return wf


def _skip_current_stage(wf, reason: str = "Auto-skip"):
    """
    Advances the workflow by skipping the *current* stage.
    Works with common patterns:
      - wf.current_stage_order (int)
      - wf.stages (related manager) with per-instance records having `order` and `status`
    Returns (changed: bool, finished: bool)
    """
    # Try to fetch the current stage instance
    current_order = getattr(wf, "current_stage_order", None)
    if current_order is None:
        return False, False

    # Many setups expose something like wf.stage_instances / wf.stages / wf.workflowstages
    stages_rel = getattr(wf, "stages", None) or getattr(wf, "stage_instances", None)
    if stages_rel is None:
        return False, False

    cur = stages_rel.filter(order=current_order).first()
    if not cur:
        return False, False

    # If your stage instance has a status field, mark it skipped (or approved)
    if hasattr(cur, "status"):
        if cur.status in ("approved", "skipped"):
            # Already not actionable; attempt to advance pointer if engine allows
            pass
        else:
            cur.status = "skipped"
            # Optional: if you store audit trails/comments
            if hasattr(cur, "system_comment"):
                cur.system_comment = (cur.system_comment or "") + f"\n[{reason}]"
            cur.save(update_fields=[f for f in ("status", "system_comment") if hasattr(cur, f)])

    # Advance the workflow pointer to the next stage
    # If your engine has a dedicated method (e.g. wf.advance_to_next_stage()),
    # prefer calling that instead.
    max_order = stages_rel.aggregate(Max("order"))["order__max"] or 0
    if current_order >= max_order:
        # we just completed the last stage → workflow finished
        if hasattr(wf, "is_completed"):
            setattr(wf, "is_completed", True)
            wf.save(update_fields=["is_completed"])
        else:
            # Some engines mark completion with a sentinel order like None/0 or keep last
            setattr(wf, "current_stage_order", current_order + 1)
            wf.save(update_fields=["current_stage_order"])
        return True, True

    # Move to the next stage
    setattr(wf, "current_stage_order", current_order + 1)
    wf.save(update_fields=["current_stage_order"])
    return True, False


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