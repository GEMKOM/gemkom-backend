# overtime/approval_service.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.contrib.auth.models import User
from approvals.models import ApprovalPolicy, ApprovalWorkflow
from approvals.resolvers import resolve_approvers_for_stage
from approvals.services import (
    create_workflow,
    record_decision,
    auto_bypass_self_approver,
)
from organization.services import get_dept_members
from .models import OvertimeRequest

from notifications.service import notify, bulk_notify, render_notification
from notifications.models import Notification


OVERTIME_SUBJECT_TYPE = "overtime_request"


def _dedupe_ordered(ids: list[int]) -> list[int]:
    seen, ordered = set(), []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


# --------- Policy selection ---------
def pick_policy_for_overtime(_ot: OvertimeRequest):
    return (ApprovalPolicy.objects
            .filter(is_active=True, subject_type=OVERTIME_SUBJECT_TYPE)
            .order_by("selection_priority")
            .first())


# --------- Helpers ---------
def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)


def _ot_title(ot: OvertimeRequest):
    s = ot.start_at.strftime("%Y-%m-%d %H:%M")
    e = ot.end_at.strftime("%Y-%m-%d %H:%M")
    return f"{s} → {e} / {ot.duration_hours} saat"


def _ot_frontend_url(ot: OvertimeRequest):
    return f"https://ofis.gemcore.com.tr/general/overtime/pending/?request={ot.id}"


def _notify_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    try:
        ot = OvertimeRequest.objects.get(id=wf.object_id)
    except OvertimeRequest.DoesNotExist:
        return
    approvers = _users_from_ids(stage.approver_user_ids or [])
    if not approvers.exists():
        return
    ctx = {
        'ot_id':              ot.id,
        'ot_title':           _ot_title(ot),
        'stage_name':         stage.name,
        'required_approvals': stage.required_approvals,
        'requestor':          getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)(),
        'team':               ot.team or '—',
        'reason':             ot.reason or '—',
    }
    title, body, link = render_notification(Notification.OT_APPROVAL_REQUESTED, ctx)
    bulk_notify(
        users=approvers,
        notification_type=Notification.OT_APPROVAL_REQUESTED,
        title=title,
        body=body,
        link=link,
        source_type='overtime_request',
        source_id=ot.id,
    )


def _notify_requester(ot: OvertimeRequest, status_str: str, comment: str = ""):
    notification_type = Notification.OT_APPROVED if status_str == "Onaylandı" else Notification.OT_REJECTED
    ctx = {
        'ot_id':    ot.id,
        'ot_title': _ot_title(ot),
        'comment':  comment,
        'requestor': getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)(),
        'team':     ot.team or '—',
        'entries_summary': '',
    }
    title, body, link = render_notification(notification_type, ctx)
    notify(
        user=ot.requester,
        notification_type=notification_type,
        title=title,
        body=body,
        link=link,
        source_type='overtime_request',
        source_id=ot.id,
    )


def _notify_hr_on_approved(ot: OvertimeRequest):
    hr_users = get_dept_members('human_resources')
    if not hr_users.exists():
        return
    lines = [
        f"Talep No: #{ot.id}",
        f"Talep Eden: {getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)()}",
        f"Takım: {ot.team or '—'}",
        f"Neden: {ot.reason or '—'}",
        f"Başlangıç: {ot.start_at.strftime('%Y-%m-%d %H:%M')}",
        f"Bitiş: {ot.end_at.strftime('%Y-%m-%d %H:%M')}",
        f"Süre: {ot.duration_hours} saat",
        "",
        "Onaylanan Kişi/Dönem Kalemleri:",
    ]
    approved_entries = ot.entries.filter(status="approved")
    for e in approved_entries:
        uname = getattr(e.user, "get_full_name", lambda: getattr(e.user, "username", str(e.user_id)))()
        lines.append(f" - {uname} | İş No: {e.job_no or '—'} | Açıklama: {e.description or '—'}")
    rejected_entries = ot.entries.filter(status="rejected")
    if rejected_entries.exists():
        lines.append("")
        lines.append("Reddedilen Kalemler:")
        for e in rejected_entries:
            uname = getattr(e.user, "get_full_name", lambda: getattr(e.user, "username", str(e.user_id)))()
            lines.append(f" - {uname} | İş No: {e.job_no or '—'}")
    ctx = {
        'ot_id':           ot.id,
        'ot_title':        _ot_title(ot),
        'comment':         '',
        'requestor':       getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)(),
        'team':            ot.team or '—',
        'entries_summary': "\n".join(lines),
    }
    title, body, link = render_notification(Notification.OT_APPROVED, ctx)
    bulk_notify(
        users=hr_users,
        notification_type=Notification.OT_APPROVED,
        title=title,
        body=body,
        link=link,
        source_type='overtime_request',
        source_id=ot.id,
    )


# --------- Skip stages that have no approvers ---------
def _skip_empty_stages(wf: ApprovalWorkflow) -> bool:
    changed = False
    while True:
        stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not stage:
            break
        approvers = stage.approver_user_ids or []
        if approvers:
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


# --------- Submit OT ---------
@transaction.atomic
def submit_overtime_request(ot: OvertimeRequest, by_user):
    policy = pick_policy_for_overtime(ot)
    if not policy or not policy.stages.exists():
        raise ValueError("Uygun bir onay politikası (mesai) bulunamadı.")

    stages_qs = policy.stages.all().order_by("order")
    snapshot = {
        "policy": {"id": policy.id, "name": policy.name},
        "stages": [
            {
                "order": s.order,
                "name": s.name,
                "required_approvals": s.required_approvals,
                "users": list(s.approver_users.values_list("id", flat=True)),
            }
            for s in stages_qs
        ],
        "overtime": {
            "id": ot.id,
            "requester_id": ot.requester_id,
            "team": ot.team,
            "reason": ot.reason,
            "start_at": ot.start_at.isoformat(),
            "end_at": ot.end_at.isoformat(),
            "duration_hours": str(ot.duration_hours),
            "entries": [
                {"user_id": e.user_id, "job_no": e.job_no, "description": e.description}
                for e in ot.entries.all()
            ],
        },
    }

    requester = ot.requester

    def _builder(stage, _subject):
        u_ids = resolve_approvers_for_stage(stage, requester)
        return list(dict.fromkeys(u_ids)), []

    wf = create_workflow(ot, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

    finished = _skip_empty_stages(wf)
    if finished:
        ot.status = "approved"
        ot.save(update_fields=["status"])
        _notify_requester(ot, "Onaylandı", "(Otomatik geçiş – boş aşamalar)")
        return wf

    changed, finished = auto_bypass_self_approver(wf, ot.requester_id)
    if finished:
        ot.status = "approved"
        ot.save(update_fields=["status"])
        _notify_requester(ot, "Onaylandı", "(Otomatik geçiş – self-bypass)")
        return wf

    if changed or wf.current_stage_order == 1:
        _notify_approvers_for_current_stage(wf, reason="Talep gönderildi")
    return wf


# --------- Decide on OT ---------
@transaction.atomic
def decide(ot: OvertimeRequest, user, approve: bool, comment: str = ""):
    wf, stage, outcome = record_decision(ot, user, approve, comment)

    if outcome == "rejected":
        ot.status = "rejected"
        ot.save(update_fields=["status"])
        # Whole request rejected -> every still-open entry is rejected too.
        ot.entries.filter(status="pending").update(status="rejected")
        _notify_requester(ot, "Reddedildi", comment or "")
        return wf

    if outcome == "moved":
        _notify_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        # Finalize per-entry decisions: any entry not explicitly rejected during
        # the flow is approved. If ALL entries ended rejected, the request is a
        # full rejection rather than an approval.
        ot.entries.filter(status="pending").update(status="approved")
        total = ot.entries.count()
        rejected = ot.entries.filter(status="rejected").count()

        if total > 0 and rejected == total:
            ot.status = "rejected"
            ot.save(update_fields=["status"])
            _notify_requester(ot, "Reddedildi", comment or "(Tüm kalemler reddedildi)")
            return wf

        ot.status = "approved"
        ot.save(update_fields=["status"])
        _notify_requester(ot, "Onaylandı", "")
        _notify_hr_on_approved(ot)
        return wf

    return wf


# --------- Retract entries after approval ---------
def _notify_requester_entries_removed(ot: OvertimeRequest, count: int, comment: str = ""):
    title = f"Mesai talebi güncellendi (#{ot.id})"
    body = f"{count} kişi/kalem onaylı mesaiden çıkarıldı."
    if comment:
        body += f" Açıklama: {comment}"
    notify(
        user=ot.requester,
        notification_type=Notification.OT_REJECTED,
        title=title,
        body=body,
        link=_ot_frontend_url(ot),
        source_type='overtime_request',
        source_id=ot.id,
    )


@transaction.atomic
def reject_entries(ot: OvertimeRequest, user, entry_ids, comment: str = ""):
    """
    Reject individual participant entries on an already-decided request (used by
    approvers to retract people after approval). Only entries not already
    rejected are affected. If every entry ends rejected the whole request flips
    to 'rejected'; otherwise it stays approved with fewer participants and HR is
    re-notified so payroll stays in sync.

    Returns (ot, number_of_entries_rejected).
    """
    updated = (
        ot.entries.filter(id__in=entry_ids)
        .exclude(status="rejected")
        .update(status="rejected", decided_by=user, decided_at=timezone.now())
    )
    if not updated:
        return ot, 0

    total = ot.entries.count()
    rejected = ot.entries.filter(status="rejected").count()

    if total > 0 and rejected == total:
        if ot.status != "rejected":
            ot.status = "rejected"
            ot.save(update_fields=["status"])
        _notify_requester(ot, "Reddedildi", comment or "(Tüm kalemler reddedildi)")
    else:
        _notify_requester_entries_removed(ot, updated, comment)
        if ot.status == "approved":
            _notify_hr_on_approved(ot)  # re-send updated approved/rejected breakdown

    return ot, updated
