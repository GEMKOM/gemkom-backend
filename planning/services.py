# planning/services.py
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from .models import DepartmentRequest, PlanningRequest, PlanningRequestItem
from approvals.services import (
    create_workflow,
    get_workflow,
    record_decision,
    resolve_group_user_ids,
    auto_bypass_self_approver,
)
from approvals.models import ApprovalPolicy, ApprovalStageInstance, ApprovalWorkflow
from core.emails import send_plain_email
from users.helpers import _team_manager_user_ids


@transaction.atomic
def create_planning_request_from_department(dept_request: DepartmentRequest, created_by_user):
    """
    Planning creates a new PlanningRequest by mapping DepartmentRequest items to catalog Items.

    Workflow:
    1. Planning reviews approved DepartmentRequest
    2. Maps each raw item description to an actual catalog Item (creates if needed)
    3. Creates PlanningRequest with properly structured items

    This function creates the shell. Planning then adds/edits PlanningRequestItems manually.
    """
    if dept_request.status != 'approved':
        raise ValidationError("Can only create planning requests from approved department requests.")

    # Create shell
    planning_request = PlanningRequest.objects.create(
        title=dept_request.title,
        description=dept_request.description,
        needed_date=dept_request.needed_date,
        department_request=dept_request,
        created_by=created_by_user,
        priority=dept_request.priority,
        status='ready',
    )

    # Mark department request as transferred
    dept_request.status = 'transferred'
    dept_request.save(update_fields=['status'])

    return planning_request


@transaction.atomic
def create_standalone_planning_request(
    title: str,
    description: str,
    needed_date,
    priority: str,
    created_by
) -> PlanningRequest:
    """
    Create a standalone PlanningRequest without a DepartmentRequest.

    Used when planning team needs to create requests directly without
    going through the department request workflow.
    """
    planning_request = PlanningRequest.objects.create(
        title=title,
        description=description,
        needed_date=needed_date,
        department_request=None,
        created_by=created_by,
        priority=priority,
        status='ready',
    )

    return planning_request


# DEPRECATED: This function is no longer used
# Planning requests are now attached to purchase requests during PR creation
# instead of being converted 1:1
#
# @transaction.atomic
# def convert_planning_request_to_purchase_request(
#     planning_request: PlanningRequest,
#     converted_by_user
# ) -> PurchaseRequest:
#     """
#     DEPRECATED: Use PurchaseRequestCreateSerializer with planning_request_ids instead.
#
#     This function previously converted a single planning request to a purchase request.
#     Now, multiple planning requests can be attached to one purchase request during creation.
#     """
#     pass


@transaction.atomic
def mark_planning_request_ready(planning_request: PlanningRequest):
    """
    Planning marks the request as ready for procurement.
    Validates that all items are properly mapped.
    """
    if planning_request.status != 'draft':
        raise ValidationError("Can only mark draft planning requests as ready.")

    if not planning_request.items.exists():
        raise ValidationError("Cannot mark empty planning request as ready.")

    # Validate all items
    for pl_item in planning_request.items.all():
        if not pl_item.item:
            raise ValidationError("All items must be mapped to catalog items.")
        if pl_item.quantity <= 0:
            raise ValidationError("All items must have positive quantities.")
        if not pl_item.job_no:
            raise ValidationError("All items must have a job number.")

    planning_request.status = 'ready'
    planning_request.ready_at = timezone.now()
    planning_request.save(update_fields=['status', 'ready_at'])

    return planning_request


# ===== Department Request Approval Services =====

# ------- Config -------
DEPARTMENT_REQUEST_POLICY_NAME = "Department Request – Default"
DEPARTMENT_HEAD_STAGE_ORDER = 1  # Stage #1 = Department Head


def _dedupe_ordered(ids: list[int]) -> list[int]:
    seen, ordered = set(), []
    for uid in ids:
        if uid not in seen:
            seen.add(uid)
            ordered.append(uid)
    return ordered


# --------- Policy selection for Department Requests ---------
def pick_policy_for_department_request(dr: DepartmentRequest):
    """
    Find the appropriate approval policy for a department request by name.
    """
    return (ApprovalPolicy.objects
            .filter(is_active=True, name=DEPARTMENT_REQUEST_POLICY_NAME)
            .order_by("selection_priority")
            .first())


# --------- Helper functions ---------
def _resolve_manager_team(team):
    """
    Map a department/team to the managing team whose managers should approve.
    Examples:
      - cutting -> planning
      - warehouse -> planning
      - machining -> manufacturing
      - maintenance -> manufacturing
      - welding -> manufacturing
      - planning/manufacturing -> themselves
      - other/unknown -> itself (fallback)
    """
    if not team:
        return None
    t = str(team).strip().lower()
    mapping = {
        "cutting": "planning",
        "warehouse": "planning",
        "planning": "planning",
        "machining": "manufacturing",
        "maintenance": "manufacturing",
        "welding": "manufacturing",
        "manufacturing": "manufacturing",
    }
    return mapping.get(t, t)

def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)


def _approver_emails_for_stage(stage: ApprovalStageInstance):
    qs = _users_from_ids(stage.approver_user_ids or [])
    return list(qs.exclude(email__isnull=True).exclude(email="").values_list("email", flat=True))


def _dr_title(dr: DepartmentRequest):
    return getattr(dr, "title", f"DR-{dr.id}")


def _dr_frontend_url(dr: DepartmentRequest):
    return f"https://ofis.gemcore.com.tr/general/department-requests/?request={dr.request_number}"


def _email_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    dr = DepartmentRequest.objects.get(id=wf.object_id)
    to_list = _approver_emails_for_stage(stage)
    if not to_list:
        return
    subject = f"[Onay Gerekli] Departman Talebi #{dr.id} – {_dr_title(dr)}"
    body = (
        f"Merhaba,\n\n"
        f"Departman talebi (#{dr.id} – {_dr_title(dr)}) için onayınız bekleniyor.\n"
        f"Aşama: {stage.name} (Gerekli onay sayısı: {stage.required_approvals})\n"
        f"Öncelik: {getattr(dr, 'priority', '—')}\n"
        f"Talep Eden: {getattr(dr.requestor, 'get_full_name', lambda: dr.requestor.username)() if getattr(dr, 'requestor', None) else '—'}\n\n"
        f"İncelemek için: {_dr_frontend_url(dr)}\n\n"
        f"Not: Bu bildirim nedeni: {reason}."
    )
    send_plain_email(subject, body, to_list)


def _email_requestor_on_final(dr: DepartmentRequest, status_str: str, comment: str = ""):
    if not getattr(dr, "requestor", None):
        return
    to = [dr.requestor.email] if getattr(dr.requestor, "email", "") else []
    if not to:
        return
    subject = f"[Departman Talebi {status_str}] DR #{dr.id} – {_dr_title(dr)}"
    body = (
        f"Merhaba,\n\n"
        f"Departman talebiniz (#{dr.id} – {_dr_title(dr)}) {status_str.lower()}.\n"
        f"{('Not: ' + comment) if comment else ''}\n\n"
        f"Detay: {_dr_frontend_url(dr)}"
    )
    send_plain_email(subject, body, to)


def _planning_emails():
    """Get emails of planning department users"""
    return list(
        User.objects.filter(is_active=True, profile__team="planning")
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def _email_planning_on_approval(dr: DepartmentRequest):
    """Notify planning department when a department request is approved"""
    to = _planning_emails()
    if not to:
        return
    subject = f"[Yeni Departman Talebi Onaylandı] DR #{dr.id} – {_dr_title(dr)}"
    body = (
        f"Merhaba Planlama,\n\n"
        f"Departman talebi (DR #{dr.id} – {_dr_title(dr)}) onaylandı ve ERP'ye aktarılmayı bekliyor.\n"
        f"Departman: {dr.department}\n"
        f"Talep Eden: {dr.requestor.get_full_name() if dr.requestor else '—'}\n"
        f"Öncelik: {dr.get_priority_display()}\n\n"
        f"Detay: {_dr_frontend_url(dr)}\n\n"
        f"Lütfen bu talebi ERP'ye aktararak satınalma sürecini başlatın."
    )
    send_plain_email(subject, body, to)


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


# --------- Submit Department Request ---------
@transaction.atomic
def submit_department_request(dr: DepartmentRequest, by_user):
    """
    Submit a department request for approval.
    Stage 1: Department head (auto-resolved from dr.department)
    Stage 2+: Policy-configured approvers (e.g., planning team)
    """
    policy = pick_policy_for_department_request(dr)
    if not policy or not policy.stages.exists():
        raise ValueError("Uygun bir onay politikası (departman talebi) bulunamadı.")

    # Build snapshot
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
        "department_request": {
            "id": dr.id,
            "requestor_id": dr.requestor_id,
            "department": dr.department,
            "title": dr.title,
            "priority": dr.priority,
        },
    }

    def _builder_with_mapping(stage, _subject):
        # Stage 1: merge policy approvers with managing-team managers
        if stage.order == DEPARTMENT_HEAD_STAGE_ORDER:
            manager_team = _resolve_manager_team(dr.department)
            mapped_manager_ids = _team_manager_user_ids(manager_team or dr.department)
            if not mapped_manager_ids and manager_team and manager_team != dr.department:
                mapped_manager_ids = _team_manager_user_ids(dr.department)

            # Include users and groups from the policy stage as well
            stage_user_ids = list(stage.approver_users.values_list("id", flat=True))
            stage_group_ids = list(stage.approver_groups.values_list("id", flat=True))
            stage_group_user_ids = resolve_group_user_ids(stage_group_ids)

            u_ids = mapped_manager_ids + stage_user_ids + stage_group_user_ids
            # keep group ids for traceability, although engine relies on user ids
            return _dedupe_ordered(u_ids), stage_group_ids

        # For all later stages, use the configured assignments (users + expanded groups)
        u_ids = list(stage.approver_users.values_list("id", flat=True))
        g_ids = list(stage.approver_groups.values_list("id", flat=True))
        u_ids += resolve_group_user_ids(g_ids)

        # Safety fallback (shouldn't trigger if policy is set correctly)
        if not u_ids:
            u_ids = list(User.objects.filter(is_active=True, is_superuser=True).values_list("id", flat=True))

        return _dedupe_ordered(u_ids), g_ids

    wf = create_workflow(dr, policy, snapshot=snapshot, approver_user_ids_builder=_builder_with_mapping)

    # Update status
    dr.status = 'submitted'
    dr.submitted_at = timezone.now()
    dr.save(update_fields=['status', 'submitted_at'])

    # 1) Skip any initial stages with no approvers (e.g., departments without a manager)
    finished = _skip_empty_stages(wf)
    if finished:
        dr.status = "approved"
        dr.save(update_fields=["status"])
        _email_requestor_on_final(dr, "Onaylandı", "(Otomatik geçiş – boş aşamalar)")
        _email_planning_on_approval(dr)
        return wf

    # 2) If requester is among approvers, auto-bypass them
    changed, finished = auto_bypass_self_approver(wf, dr.requestor_id)
    if finished:
        dr.status = "approved"
        dr.save(update_fields=["status"])
        _email_requestor_on_final(dr, "Onaylandı", "(Otomatik geçiş – self-bypass)")
        _email_planning_on_approval(dr)
        return wf

    if changed or wf.current_stage_order == 1:
        _email_approvers_for_current_stage(wf, reason="Talep gönderildi")

    return wf


# --------- Decide on Department Request ---------
@transaction.atomic
def decide_department_request(dr: DepartmentRequest, user, approve: bool, comment: str = ""):
    """
    Record an approval/rejection decision on a department request.
    """
    wf, stage, outcome = record_decision(dr, user, approve, comment)

    if outcome == "rejected":
        dr.status = "rejected"
        dr.rejection_reason = comment
        dr.save(update_fields=["status", "rejection_reason"])
        _email_requestor_on_final(dr, status_str="Reddedildi", comment=comment)
        return wf

    if outcome == "moved":
        # Moved to next stage
        _email_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        # All stages approved
        dr.status = "approved"
        dr.approved_by = user
        dr.approved_at = timezone.now()
        dr.save(update_fields=["status", "approved_by", "approved_at"])

        _email_requestor_on_final(dr, status_str="Onaylandı", comment="")
        _email_planning_on_approval(dr)
        return wf

    # "pending" → quorum not yet reached
    return wf
