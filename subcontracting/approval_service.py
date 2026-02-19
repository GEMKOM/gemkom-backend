from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone

from approvals.services import create_workflow, record_decision, resolve_group_user_ids
from approvals.models import ApprovalPolicy, ApprovalWorkflow

from .models import SubcontractorStatement
from .services.statements import advance_billed_progress
from core.emails import send_plain_email


# ---------------------------------------------------------------------------
# Policy selection
# ---------------------------------------------------------------------------

def pick_policy_for_statement(statement: SubcontractorStatement) -> ApprovalPolicy | None:
    """
    Select an active approval policy for subcontractor statements.
    Looks for any policy with 'taseron' or 'subcontract' in its name (case-insensitive).
    Falls back to any active policy with no amount constraints if none found.
    """
    from django.db.models import Q
    qs = ApprovalPolicy.objects.filter(is_active=True).filter(
        Q(name__icontains='taseron') | Q(name__icontains='subcontract')
    )
    return qs.order_by('selection_priority').first()


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def _approver_emails_for_current_stage(wf: ApprovalWorkflow) -> list[str]:
    if wf.is_complete or wf.is_rejected:
        return []
    stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
    if not stage or stage.is_complete or stage.is_rejected:
        return []
    user_ids = stage.approver_user_ids or []
    return list(
        User.objects.filter(id__in=user_ids, is_active=True)
        .exclude(email='').exclude(email__isnull=True)
        .values_list('email', flat=True)
    )


def _email_approvers(wf: ApprovalWorkflow, statement: SubcontractorStatement, reason: str = ''):
    to = _approver_emails_for_current_stage(wf)
    if not to:
        return
    subject = (
        f"[Onay Gerekli] Taşeron Hakedişi – "
        f"{statement.subcontractor.name} {statement.year}/{statement.month:02d}"
    )
    body = (
        f"Merhaba,\n\n"
        f"{statement.subcontractor.name} taşeronuna ait "
        f"{statement.year}/{statement.month:02d} dönemi hakedişi onayınızı bekliyor.\n"
        f"Toplam Tutar: {statement.currency} {statement.grand_total}\n"
        f"{('Neden: ' + reason) if reason else ''}\n\n"
        f"Lütfen sisteme girerek inceleyiniz."
    )
    send_plain_email(subject, body, to)


def _email_on_final(statement: SubcontractorStatement, status_str: str, comment: str = ''):
    if not statement.created_by or not getattr(statement.created_by, 'email', ''):
        return
    subject = (
        f"[Taşeron Hakedişi {status_str}] "
        f"{statement.subcontractor.name} {statement.year}/{statement.month:02d}"
    )
    body = (
        f"Merhaba,\n\n"
        f"Taşeron hakedişi ({statement.subcontractor.name} – "
        f"{statement.year}/{statement.month:02d}) {status_str.lower()}.\n"
        f"Toplam Tutar: {statement.currency} {statement.grand_total}\n"
        f"{('Not: ' + comment) if comment else ''}"
    )
    send_plain_email(subject, body, [statement.created_by.email])


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def submit_statement(statement: SubcontractorStatement, by_user: User) -> ApprovalWorkflow:
    """Submit a statement for approval. Mirrors procurement.submit_purchase_request."""
    if statement.status != 'draft':
        raise ValueError(
            f"Yalnızca 'taslak' durumundaki hakedişler gönderilebilir. "
            f"Mevcut durum: {statement.get_status_display()}"
        )
    if statement.grand_total <= 0:
        raise ValueError("Toplam tutarı sıfır veya negatif olan hakediş gönderilemez.")

    with transaction.atomic():
        policy = pick_policy_for_statement(statement)
        if not policy or not policy.stages.exists():
            raise ValueError(
                "Taşeron hakedişi için geçerli bir onay politikası bulunamadı. "
                "Lütfen yöneticinizle iletişime geçin."
            )

        stages_qs = policy.stages.all().order_by('order')
        snapshot = {
            'policy': {'id': policy.id, 'name': policy.name},
            'stages': [
                {
                    'order': s.order,
                    'name': s.name,
                    'required_approvals': s.required_approvals,
                    'users': list(s.approver_users.values_list('id', flat=True)),
                    'groups': list(s.approver_groups.values_list('id', flat=True)),
                }
                for s in stages_qs
            ],
        }

        def _builder(stage, _subject):
            u_ids = list(stage.approver_users.values_list('id', flat=True))
            g_ids = list(stage.approver_groups.values_list('id', flat=True))
            u_ids += resolve_group_user_ids(g_ids)
            seen, ordered = set(), []
            for uid in u_ids:
                if uid not in seen:
                    seen.add(uid)
                    ordered.append(uid)
            return ordered, g_ids

        wf = create_workflow(statement, policy, snapshot=snapshot, approver_user_ids_builder=_builder)

        statement.status = 'submitted'
        statement.submitted_at = timezone.now()
        statement.save(update_fields=['status', 'submitted_at'])

    # Emails outside transaction
    _email_approvers(wf, statement, reason='Hakediş gönderildi')
    return wf


# ---------------------------------------------------------------------------
# Decide (approve / reject)
# ---------------------------------------------------------------------------

def decide_statement(
    statement: SubcontractorStatement,
    user: User,
    approve: bool,
    comment: str = '',
) -> ApprovalWorkflow:
    """Approve or reject a statement. Mirrors procurement.decide."""
    if statement.status != 'submitted':
        raise ValueError(
            f"Yalnızca 'onay bekliyor' durumundaki hakedişler için karar verilebilir. "
            f"Mevcut durum: {statement.get_status_display()}"
        )

    with transaction.atomic():
        wf, stage, outcome = record_decision(statement, user, approve, comment)

        if outcome == 'rejected':
            statement.status = 'rejected'
            statement.save(update_fields=['status'])
            return wf

        if outcome == 'completed':
            statement.status = 'approved'
            statement.save(update_fields=['status'])
            # Advance last_billed_progress on all assignments
            advance_billed_progress(statement)

        # outcome == 'pending' or 'moved': status stays 'submitted'

    # Emails outside transaction
    if outcome == 'moved':
        _email_approvers(wf, statement, reason=f'Önceki aşama onaylandı (#{stage.order})')
    elif outcome == 'completed':
        _email_on_final(statement, status_str='Onaylandı', comment=comment)
    elif outcome == 'rejected':
        _email_on_final(statement, status_str='Reddedildi', comment=comment)

    return wf
