# overtime/approval_service.py
from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import User
from approvals.models import ApprovalPolicy, ApprovalStageInstance, ApprovalWorkflow
from approvals.services import (
    create_workflow,
    record_decision,
    auto_bypass_self_approver,
    resolve_group_user_ids,
)
from core.emails import send_plain_email
from users.helpers import _team_manager_user_ids
from .models import OvertimeRequest


# ------- Config -------
         # your UserProfile.occupation value for managers
OVERTIME_POLICY_NAME    = "Overtime – Default"  # pick policy explicitly by name
TEAM_MANAGER_STAGE_ORDER = 1                    # Stage #1 = Team Manager; Stage #2+ = policy-configured approvers
TEAM_HR_CODE = "human_resources" 

def _dedupe_ordered(ids: list[int]) -> list[int]:
    seen, ordered = set(), []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


# --------- Policy selection (by name) ---------
def pick_policy_for_overtime(_ot: OvertimeRequest):
    return (ApprovalPolicy.objects
            .filter(is_active=True, name=OVERTIME_POLICY_NAME)
            .order_by("selection_priority")
            .first())


# --------- Emails ---------
def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)

def _emails_from_queryset(qs):
    return list(qs.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True))

def _hr_recipient_emails():
    """
    All active users in the Human Resources team.
    """
    qs = User.objects.filter(is_active=True, profile__team=TEAM_HR_CODE)
    return _emails_from_queryset(qs)

def _approver_emails_for_stage(stage: ApprovalStageInstance):
    qs = _users_from_ids(stage.approver_user_ids or [])
    return list(qs.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True))

def _ot_title(ot: OvertimeRequest):
    s = ot.start_at.strftime("%Y-%m-%d %H:%M"); e = ot.end_at.strftime("%Y-%m-%d %H:%M")
    return f"{s} → {e} / {ot.duration_hours} saat"

def _ot_frontend_url(ot: OvertimeRequest):
    return f"https://ofis.gemcore.com.tr/general/overtime/pending/?request={ot.id}"

def _email_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    try:
        ot = OvertimeRequest.objects.get(id=wf.object_id)
    except OvertimeRequest.DoesNotExist:
        return
    to_list = _approver_emails_for_stage(stage)
    if not to_list:
        return
    subject = f"[Onay Gerekli] Mesai Talebi #{ot.id} – {_ot_title(ot)}"
    body = (
        f"Merhaba,\n\n"
        f"Mesai talebi (#{ot.id}) için onayınız bekleniyor.\n"
        f"Aşama: {stage.name} (Gerekli onay sayısı: {stage.required_approvals})\n"
        f"Talep Eden: {getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)()}\n"
        f"Takım: {ot.team or '—'}\n"
        f"Neden: {ot.reason or '—'}\n\n"
        f"İncelemek için: {_ot_frontend_url(ot)}\n\n"
        f"Not: Bildirim nedeni: {reason}."
    )
    send_plain_email(subject, body, to_list)

def _email_requester(ot: OvertimeRequest, status_str: str, comment: str = ""):
    to = [ot.requester.email] if getattr(ot.requester, "email", "") else []
    if not to:
        return
    subject = f"[Mesai Talebi {status_str}] OT #{ot.id} – {_ot_title(ot)}"
    body = (
        f"Merhaba,\n\n"
        f"Mesai talebiniz (#{ot.id}) {status_str.lower()}.\n"
        f"{('Not: ' + comment) if comment else ''}\n\n"
        f"Detay: {_ot_frontend_url(ot)}"
    )
    send_plain_email(subject, body, to)

def _email_hr_on_approved(ot: OvertimeRequest):
    """
    Notify HR when an overtime request is fully approved.
    """
    to_list = _hr_recipient_emails()
    if not to_list:
        return
    subject = f"[Bilgi] Onaylanan Mesai Talebi #{ot.id} – {_ot_title(ot)}"
    lines = [
        f"Talep No: #{ot.id}",
        f"Talep Eden: {getattr(ot.requester, 'get_full_name', lambda: ot.requester.username)()}",
        f"Takım: {ot.team or '—'}",
        f"Neden: {ot.reason or '—'}",
        f"Başlangıç: {ot.start_at.strftime('%Y-%m-%d %H:%M')}",
        f"Bitiş: {ot.end_at.strftime('%Y-%m-%d %H:%M')}",
        f"Süre: {ot.duration_hours} saat",
        "",
        "Kişi/Dönem Kalemleri:",
    ]
    for e in ot.entries.all():
        # You can enrich this if you have names via select_related('user') on entries
        uname = getattr(e.user, "get_full_name", lambda: getattr(e.user, "username", str(e.user_id)))()
        lines.append(f" - {uname} | İş No: {e.job_no or '—'} | Açıklama: {e.description or '—'}")

    lines += ["", f"Detay: {_ot_frontend_url(ot)}"]
    body = " \n".join(lines)
    send_plain_email(subject, body, to_list)

# --------- Skip stages that have no approvers ---------
def _skip_empty_stages(wf: ApprovalWorkflow) -> bool:
    """
    Auto-complete any leading stages that have zero approvers.
    Returns True if workflow finished; otherwise False.
    """
    changed = False
    while True:
        stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not stage:
            break
        approvers = stage.approver_user_ids or []
        if approvers:
            break
        # no approvers -> mark complete and advance
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


# --------- Submit OT (order-based routing) ---------
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
                "order": s.order, "name": s.name,
                "required_approvals": s.required_approvals,
                "users": list(s.approver_users.values_list("id", flat=True)),
                "groups": list(s.approver_groups.values_list("id", flat=True)),
            }
            for s in stages_qs
        ],
        "overtime": {
            "id": ot.id, "requester_id": ot.requester_id, "team": ot.team, "reason": ot.reason,
            "start_at": ot.start_at.isoformat(), "end_at": ot.end_at.isoformat(),
            "duration_hours": str(ot.duration_hours),
            "entries": [
                {"user_id": e.user_id, "job_no": e.job_no, "description": e.description}
                for e in ot.entries.all()
            ],
        },
    }

    def _builder(stage, _subject):
        """
        Stage 1 (order == TEAM_MANAGER_STAGE_ORDER):
            - Resolve team manager(s) for ot.team.
            - If none → return [] (stage will be auto-skipped).
        Stage 2+:
            - Use the policy-configured users/groups on the stage (e.g., your "Overtime Approvers" group).
        """
        if stage.order == TEAM_MANAGER_STAGE_ORDER:
            u_ids = _team_manager_user_ids(ot.team)  # may be empty → will be skipped by _skip_empty_stages
            return _dedupe_ordered(u_ids), []

        # For all later stages, use the configured assignments
        u_ids = list(stage.approver_users.values_list("id", flat=True))
        g_ids = list(stage.approver_groups.values_list("id", flat=True))
        u_ids += resolve_group_user_ids(g_ids)

        # Safety fallback (shouldn't trigger if policy is set correctly)
        if not u_ids:
            u_ids = list(User.objects.filter(is_active=True, is_superuser=True).values_list("id", flat=True))

        return _dedupe_ordered(u_ids), []

    wf = create_workflow(ot, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

    # 1) Skip any initial stages with no approvers (e.g., teams without a manager)
    finished = _skip_empty_stages(wf)
    if finished:
        ot.status = "approved"
        ot.save(update_fields=["status"])
        _email_requester(ot, "Onaylandı", "(Otomatik geçiş – boş aşamalar)")
        return wf

    # 2) If requester is among approvers, auto-bypass them
    changed, finished = auto_bypass_self_approver(wf, ot.requester_id)
    if finished:
        ot.status = "approved"
        ot.save(update_fields=["status"])
        _email_requester(ot, "Onaylandı", "(Otomatik geçiş – self-bypass)")
        return wf

    if changed or wf.current_stage_order == 1:
        _email_approvers_for_current_stage(wf, reason="Talep gönderildi")
    return wf


# --------- Decide on OT ---------
@transaction.atomic
def decide(ot: OvertimeRequest, user, approve: bool, comment: str = ""):
    wf, stage, outcome = record_decision(ot, user, approve, comment)

    if outcome == "rejected":
        ot.status = "rejected"
        ot.save(update_fields=["status"])
        _email_requester(ot, "Reddedildi", comment or "")
        return wf

    if outcome == "moved":
        _email_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        ot.status = "approved"
        ot.save(update_fields=["status"])
        _email_requester(ot, "Onaylandı", "")
        return wf

    return wf
