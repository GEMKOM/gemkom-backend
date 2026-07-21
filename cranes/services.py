# cranes/services.py
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from approvals.models import ApprovalPolicy, ApprovalWorkflow
from approvals.resolvers import resolve_approvers_for_stage
from approvals.services import (
    auto_bypass_self_approver,
    create_workflow,
    get_workflow,
    record_decision,
)
from notifications.models import Notification
from notifications.service import bulk_notify, notify, render_notification
from organization.models import UserGroup

from .models import CraneRequest

CRANE_REQUEST_SUBJECT_TYPE = "crane_request"
COORDINATION_GROUP_SLUG = "vinc-koordinasyon"

# Synthetic job dropdown entry ("Fabrika İşleri") that has no JobOrder row.
FACTORY_JOB_NO = "1000"


# --------- Pricing / estimate ---------

def compute_estimate(crane_type, pricing_option: str, days: int = 1, needs_rigger: bool = False, on_date=None):
    """
    Compute the cost estimate for a request from the crane type's current rate.
    Returns (total: Decimal, currency: str, breakdown: dict).
    Raises ValidationError when the type has no rate or doesn't offer the option.
    """
    rate = crane_type.current_rate(on_date)
    if not rate:
        raise ValidationError(f"'{crane_type.name}' için geçerli bir fiyat tanımı bulunamadı.")

    breakdown = {}
    if pricing_option == 'up_to_3h':
        if rate.price_up_to_3h is None:
            raise ValidationError(f"'{crane_type.name}' için 3 saate kadar fiyatı tanımlı değil.")
        base = rate.price_up_to_3h
        breakdown['base'] = {'label': '3 saate kadar', 'amount': str(base)}
    elif pricing_option == 'up_to_8h':
        if rate.price_up_to_8h is None:
            raise ValidationError(f"'{crane_type.name}' için 8 saate kadar fiyatı tanımlı değil.")
        base = rate.price_up_to_8h
        breakdown['base'] = {'label': '8 saate kadar', 'amount': str(base)}
    elif pricing_option == 'daily':
        if rate.price_per_day is None:
            raise ValidationError(f"'{crane_type.name}' için günlük fiyat tanımlı değil.")
        days = max(int(days or 1), 1)
        base = rate.price_per_day * days
        breakdown['base'] = {
            'label': f'Günlük × {days}',
            'unit_price': str(rate.price_per_day),
            'days': days,
            'amount': str(base),
        }
    else:
        raise ValidationError(f"Geçersiz fiyatlandırma seçeneği: {pricing_option}")

    total = base

    if pricing_option == 'daily' and rate.transport_fee is not None:
        total += rate.transport_fee
        breakdown['transport'] = {'label': 'Nakliye (gidiş-dönüş)', 'amount': str(rate.transport_fee)}

    if needs_rigger:
        if rate.rigger_fee is None:
            raise ValidationError(f"'{crane_type.name}' için sapancı ücreti tanımlı değil.")
        total += rate.rigger_fee
        breakdown['rigger'] = {'label': 'İlave sapancı', 'amount': str(rate.rigger_fee)}

    breakdown['total'] = str(total)
    breakdown['currency'] = rate.currency
    breakdown['rate_effective_from'] = str(rate.effective_from)
    return total, rate.currency, breakdown


# --------- Coordination team helpers ---------

def get_coordination_group():
    return UserGroup.objects.filter(slug=COORDINATION_GROUP_SLUG, is_active=True).first()


def user_can_complete(user) -> bool:
    """Coordination-team members (or admins) may record actuals / complete."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser or user.is_staff:
        return True
    group = get_coordination_group()
    if not group:
        return False
    return group.get_members().filter(id=user.id).exists()


# --------- Policy selection ---------

def pick_policy_for_crane_request(cr: CraneRequest):
    return (ApprovalPolicy.objects
            .filter(is_active=True, subject_type=CRANE_REQUEST_SUBJECT_TYPE)
            .order_by("selection_priority")
            .first())


# --------- Notification helpers ---------

def _users_from_ids(user_ids):
    if not user_ids:
        return User.objects.none()
    return User.objects.filter(id__in=user_ids, is_active=True)


def _cost_str(amount, currency) -> str:
    if amount is None:
        return '—'
    return f"{amount} {currency}"


def _base_ctx(cr: CraneRequest) -> dict:
    return {
        'cr_id': cr.id,
        'request_number': cr.request_number,
        'requestor': (cr.requestor.get_full_name() or cr.requestor.username) if cr.requestor else '—',
        'crane_type': cr.crane_type.name,
        'job_no': cr.job_no,
        'needed_date': str(cr.needed_date),
        'estimated_cost': _cost_str(cr.estimated_cost, cr.estimated_cost_currency),
        'priority': cr.get_priority_display(),
    }


def _notify_approvers_for_current_stage(wf: ApprovalWorkflow, reason: str = "pending"):
    if wf.is_complete or wf.is_rejected:
        return
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return
    cr = CraneRequest.objects.get(id=wf.object_id)
    approvers = _users_from_ids(stage.approver_user_ids or [])
    if not approvers.exists():
        return
    ctx = {
        **_base_ctx(cr),
        'stage_name': stage.name,
        'required_approvals': stage.required_approvals,
        'reason': reason,
    }
    title, body, link = render_notification(Notification.CRANE_APPROVAL_REQUESTED, ctx)
    bulk_notify(
        users=approvers,
        notification_type=Notification.CRANE_APPROVAL_REQUESTED,
        title=title,
        body=body,
        link=link,
        source_type='crane_request',
        source_id=cr.id,
    )


def _notify_requestor_on_final(cr: CraneRequest, approved: bool, comment: str = ""):
    if not getattr(cr, "requestor", None):
        return
    notification_type = Notification.CRANE_APPROVED if approved else Notification.CRANE_REJECTED
    ctx = {**_base_ctx(cr), 'comment': comment}
    title, body, link = render_notification(notification_type, ctx)
    notify(
        user=cr.requestor,
        notification_type=notification_type,
        title=title,
        body=body,
        link=link,
        source_type='crane_request',
        source_id=cr.id,
    )


def _notify_coordination_on_approval(cr: CraneRequest):
    """Notify the coordination team so they can arrange the rental with the vendor."""
    group = get_coordination_group()
    if not group:
        return
    members = group.get_members()
    if not members.exists():
        return
    ctx = {**_base_ctx(cr), 'comment': 'Lütfen kiralamayı organize edin.'}
    title, body, link = render_notification(Notification.CRANE_APPROVED, ctx)
    bulk_notify(
        users=members,
        notification_type=Notification.CRANE_APPROVED,
        title=title,
        body=body,
        link=link,
        source_type='crane_request',
        source_id=cr.id,
    )


def _notify_requestor_on_completed(cr: CraneRequest):
    if not getattr(cr, "requestor", None):
        return
    ctx = {**_base_ctx(cr), 'actual_cost': _cost_str(cr.actual_cost, cr.actual_cost_currency)}
    title, body, link = render_notification(Notification.CRANE_COMPLETED, ctx)
    notify(
        user=cr.requestor,
        notification_type=Notification.CRANE_COMPLETED,
        title=title,
        body=body,
        link=link,
        source_type='crane_request',
        source_id=cr.id,
    )


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


# --------- Submit ---------

@transaction.atomic
def submit_crane_request(cr: CraneRequest, by_user):
    policy = pick_policy_for_crane_request(cr)
    if not policy or not policy.stages.exists():
        raise ValueError("Uygun bir onay politikası (vinç talebi) bulunamadı.")

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
        "crane_request": {
            "id": cr.id,
            "requestor_id": cr.requestor_id,
            "department": cr.department,
            "crane_type": cr.crane_type.name,
            "job_no": cr.job_no,
            "estimated_cost": str(cr.estimated_cost) if cr.estimated_cost is not None else None,
            "priority": cr.priority,
        },
    }

    def _builder(stage, _subject):
        u_ids = resolve_approvers_for_stage(stage, cr.requestor)
        return list(dict.fromkeys(u_ids)), []

    wf = create_workflow(cr, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

    cr.status = 'submitted'
    cr.submitted_at = timezone.now()
    cr.save(update_fields=['status', 'submitted_at'])

    # 1) Skip any initial stages with no approvers (e.g., departments without a manager)
    finished = _skip_empty_stages(wf)
    if finished:
        cr.status = "approved"
        cr.save(update_fields=["status"])
        _notify_requestor_on_final(cr, approved=True, comment="(Otomatik geçiş – boş aşamalar)")
        _notify_coordination_on_approval(cr)
        return wf

    # 2) If requester is among approvers, auto-bypass them
    changed, finished = auto_bypass_self_approver(wf, cr.requestor_id)
    if finished:
        cr.status = "approved"
        cr.save(update_fields=["status"])
        _notify_requestor_on_final(cr, approved=True, comment="(Otomatik geçiş – self-bypass)")
        _notify_coordination_on_approval(cr)
        return wf

    if changed or wf.current_stage_order == 1:
        _notify_approvers_for_current_stage(wf, reason="Talep gönderildi")

    return wf


# --------- Decide ---------

@transaction.atomic
def decide_crane_request(cr: CraneRequest, user, approve: bool, comment: str = ""):
    """
    Record an approval/rejection decision on a crane request.
    Raises PermissionError when the user is not an approver of the current stage.
    """
    # record_decision does not verify stage membership — enforce it here.
    if not (user.is_superuser or user.is_staff):
        wf = get_workflow(cr)
        stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not stage or user.id not in (stage.approver_user_ids or []):
            raise PermissionError("Bu talebin mevcut aşamasında onay yetkiniz yok.")

    wf, stage, outcome = record_decision(cr, user, approve, comment)

    if outcome == "rejected":
        cr.status = "rejected"
        cr.rejection_reason = comment
        cr.save(update_fields=["status", "rejection_reason"])
        _notify_requestor_on_final(cr, approved=False, comment=comment)
        return wf

    if outcome == "moved":
        _notify_approvers_for_current_stage(wf, reason=f"Önceki aşama onaylandı (#{stage.order})")
        return wf

    if outcome == "completed":
        cr.status = "approved"
        cr.approved_by = user
        cr.approved_at = timezone.now()
        cr.save(update_fields=["status", "approved_by", "approved_at"])
        _notify_requestor_on_final(cr, approved=True, comment="")
        _notify_coordination_on_approval(cr)
        return wf

    # "pending" → quorum not yet reached
    return wf


# --------- Cancel ---------

@transaction.atomic
def cancel_crane_request(cr: CraneRequest, user):
    """Requestor cancels their own submitted request."""
    if cr.status != 'submitted':
        raise ValueError("Sadece onay bekleyen talepler iptal edilebilir.")
    if cr.requestor_id != user.id and not (user.is_superuser or user.is_staff):
        raise PermissionError("Sadece talep sahibi iptal edebilir.")

    try:
        wf = get_workflow(cr)
        if not wf.is_complete and not wf.is_rejected:
            wf.is_cancelled = True
            wf.save(update_fields=["is_cancelled"])
    except ApprovalWorkflow.DoesNotExist:
        pass

    cr.status = 'cancelled'
    cr.save(update_fields=['status'])
    return cr


# --------- Complete (record actuals) ---------

@transaction.atomic
def complete_crane_request(cr: CraneRequest, user, actual_quantity, actual_cost, currency: str = 'TRY'):
    """
    Coordination team records the rental's actual quantity (hours or days)
    and cost. Also allowed on already-completed requests to CORRECT the
    actuals (e.g. planned 3 hours became 8, or a late invoice differs);
    corrections keep the original completion date so the FX conversion of
    the job cost stays stable. The caller (view) triggers the job-cost
    recompute AFTER this transaction commits.
    """
    if not user_can_complete(user):
        raise PermissionError("Fiili maliyet girme yetkiniz yok (Vinç Koordinasyon).")
    if cr.status not in ('approved', 'completed'):
        raise ValueError("Fiili değerler sadece onaylanmış veya tamamlanmış taleplere girilebilir.")
    if actual_cost is None or Decimal(str(actual_cost)) < 0:
        raise ValidationError("Fiili maliyet zorunludur ve negatif olamaz.")

    is_correction = cr.status == 'completed'

    cr.actual_quantity = actual_quantity
    cr.actual_cost = Decimal(str(actual_cost))
    cr.actual_cost_currency = currency or 'TRY'
    cr.completed_by = user
    if not is_correction or cr.completed_at is None:
        cr.completed_at = timezone.now()
    cr.status = 'completed'
    cr.save(update_fields=[
        'actual_quantity', 'actual_cost', 'actual_cost_currency',
        'completed_by', 'completed_at', 'status',
    ])

    if not is_correction:
        _notify_requestor_on_completed(cr)
    return cr
