from __future__ import annotations

from django.contrib.auth.models import User, Group
from django.db import transaction

from approvals.models import ApprovalPolicy, ApprovalStageInstance, ApprovalWorkflow
from approvals.services import (
    auto_bypass_self_approver,
    create_workflow,
    record_decision,
    resolve_group_user_ids,
)
from notifications.models import Notification
from notifications.service import bulk_notify, notify, render_notification
from users.helpers import _team_manager_user_ids

from .models import VacationRequest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
VACATION_POLICY_NAME     = "Vacation – Default"
TEAM_MANAGER_STAGE_ORDER = 1
HR_GROUP_NAME            = "hr_team"


def _dedupe_ordered(ids: list[int]) -> list[int]:
    seen, ordered = set(), []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


# ---------------------------------------------------------------------------
# Policy selection
# ---------------------------------------------------------------------------
def pick_policy_for_vacation(_vr: VacationRequest):
    return (
        ApprovalPolicy.objects
        .filter(is_active=True, name=VACATION_POLICY_NAME)
        .order_by("selection_priority")
        .first()
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)


def _vr_title(vr: VacationRequest) -> str:
    leave_label = dict(vr.LEAVE_TYPE_CHOICES).get(vr.leave_type, vr.leave_type)
    return f"{leave_label} | {vr.start_date} → {vr.end_date} ({vr.duration_days} gün)"


def _vr_frontend_url(vr: VacationRequest) -> str:
    return f"https://ofis.gemcore.com.tr/general/vacation-requests/pending/?request={vr.id}"


def _notify_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    try:
        vr = VacationRequest.objects.select_related("requester").get(id=wf.object_id)
    except VacationRequest.DoesNotExist:
        return
    approvers = _users_from_ids(stage.approver_user_ids or [])
    if not approvers.exists():
        return
    ctx = {
        "vr_id":              vr.id,
        "vr_title":           _vr_title(vr),
        "stage_name":         stage.name,
        "required_approvals": stage.required_approvals,
        "requestor":          vr.requester.get_full_name() or vr.requester.username,
        "team":               vr.team or "—",
        "reason":             vr.reason or "—",
        "start_date":         str(vr.start_date),
        "end_date":           str(vr.end_date),
        "duration_days":      str(vr.duration_days),
    }
    title, body, link = render_notification(Notification.VR_APPROVAL_REQUESTED, ctx)
    bulk_notify(
        users=approvers,
        notification_type=Notification.VR_APPROVAL_REQUESTED,
        title=title,
        body=body,
        link=link,
        source_type="vacation_request",
        source_id=vr.id,
    )


def _notify_requester(vr: VacationRequest, status_str: str, comment: str = ""):
    notification_type = Notification.VR_APPROVED if status_str == "Onaylandı" else Notification.VR_REJECTED
    ctx = {
        "vr_id":         vr.id,
        "vr_title":      _vr_title(vr),
        "comment":       comment,
        "requestor":     vr.requester.get_full_name() or vr.requester.username,
        "team":          vr.team or "—",
        "start_date":    str(vr.start_date),
        "end_date":      str(vr.end_date),
        "duration_days": str(vr.duration_days),
    }
    title, body, link = render_notification(notification_type, ctx)
    notify(
        user=vr.requester,
        notification_type=notification_type,
        title=title,
        body=body,
        link=link,
        source_type="vacation_request",
        source_id=vr.id,
    )


# ---------------------------------------------------------------------------
# Skip stages that have no approvers
# ---------------------------------------------------------------------------
def _skip_empty_stages(wf: ApprovalWorkflow) -> bool:
    changed = False
    while True:
        stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not stage:
            break
        if stage.approver_user_ids:
            break
        stage.is_complete = True
        stage.save(update_fields=["is_complete"])
        wf.current_stage_order += 1
        changed = True

    last = wf.stage_instances.order_by("-order").values_list("order", flat=True).first() or 0
    if wf.current_stage_order > last:
        wf.is_complete = True
        wf.save(update_fields=["is_complete", "current_stage_order"])
        return True
    if changed:
        wf.save(update_fields=["current_stage_order"])
    return False


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
@transaction.atomic
def submit_vacation_request(vr: VacationRequest, by_user):
    policy = pick_policy_for_vacation(vr)
    if not policy or not policy.stages.exists():
        raise ValueError("Uygun bir onay politikası (izin talebi) bulunamadı.")

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
        "vacation_request": {
            "id": vr.id,
            "requester_id": vr.requester_id,
            "team": vr.team,
            "leave_type": vr.leave_type,
            "start_date": vr.start_date.isoformat(),
            "end_date": vr.end_date.isoformat(),
            "duration_days": str(vr.duration_days),
            "reason": vr.reason,
        },
    }

    def _builder(stage, _subject):
        if stage.order == TEAM_MANAGER_STAGE_ORDER:
            u_ids = _team_manager_user_ids(vr.team)
            return _dedupe_ordered(u_ids), []
        u_ids = list(stage.approver_users.values_list("id", flat=True))
        g_ids = list(stage.approver_groups.values_list("id", flat=True))
        u_ids += resolve_group_user_ids(g_ids)
        if not u_ids:
            u_ids = list(User.objects.filter(is_active=True, is_superuser=True).values_list("id", flat=True))
        return _dedupe_ordered(u_ids), []

    wf = create_workflow(vr, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

    finished = _skip_empty_stages(wf)
    if finished:
        vr.status = "approved"
        vr.save(update_fields=["status"])
        _notify_requester(vr, "Onaylandı", "(Otomatik geçiş – boş aşamalar)")
        return wf

    changed, finished = auto_bypass_self_approver(wf, vr.requester_id)
    if finished:
        vr.status = "approved"
        vr.save(update_fields=["status"])
        _notify_requester(vr, "Onaylandı", "(Otomatik geçiş – self-bypass)")
        return wf

    if changed or wf.current_stage_order == 1:
        _notify_approvers_for_current_stage(wf, reason="Talep gönderildi")
    return wf


# ---------------------------------------------------------------------------
# Decide (approve / reject)
# ---------------------------------------------------------------------------
@transaction.atomic
def decide(vr: VacationRequest, user, approve: bool, comment: str = ""):
    wf, stage, outcome = record_decision(vr, user, approve, comment)

    if outcome == "rejected":
        vr.status = "rejected"
        vr.save(update_fields=["status"])
        _notify_requester(vr, "Reddedildi", comment or "")
        return wf

    if outcome == "moved":
        _notify_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        vr.status = "approved"
        vr.save(update_fields=["status"])
        _notify_requester(vr, "Onaylandı", "")
        return wf

    return wf
