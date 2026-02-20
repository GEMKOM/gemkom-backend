from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone

from approvals.services import create_workflow, record_decision
from approvals.models import ApprovalPolicy, ApprovalStage

from .models import QCReview, NCR
from core.emails import send_plain_email


QC_REVIEW_POLICY_NAME = "KK İnceleme Onay Politikası"
NCR_POLICY_NAME = "NCR Onay Politikası"


# =============================================================================
# Helpers
# =============================================================================

def _get_qc_team_user_ids() -> list[int]:
    """Return active user IDs in the qualitycontrol team."""
    return list(
        User.objects.filter(is_active=True, profile__team='qualitycontrol')
        .values_list('id', flat=True)
    )


def _get_qc_team_emails() -> list[str]:
    return list(
        User.objects.filter(is_active=True, profile__team='qualitycontrol')
        .exclude(email='').exclude(email__isnull=True)
        .values_list('email', flat=True)
    )


def _get_or_create_policy(policy_name: str) -> ApprovalPolicy:
    """
    Get or create a named approval policy with a single stage (any QC member can approve).
    Approvers are resolved dynamically via approver_user_ids_builder at workflow creation time.
    """
    policy, created = ApprovalPolicy.objects.get_or_create(
        name=policy_name,
        defaults={'is_active': True}
    )
    if created:
        ApprovalStage.objects.create(
            policy=policy,
            order=1,
            name='Kalite Kontrol Onayı',
            required_approvals=1,
        )
    return policy


def _qc_team_builder(stage, _subject):
    """approver_user_ids_builder: returns all QC team members as approvers."""
    return _get_qc_team_user_ids(), []


# =============================================================================
# QCReview — submission and decision
# =============================================================================

def submit_for_qc_review(task, submitted_by) -> QCReview:
    """
    Submit a manufacturing task for QC review.
    Creates a QCReview and an ApprovalWorkflow targeting the QC team.

    Permission: submitted_by must belong to the task's department or qualitycontrol.
    """
    user_team = getattr(getattr(submitted_by, 'profile', None), 'team', None)
    if user_team not in (task.department, 'qualitycontrol') and not submitted_by.is_superuser:
        raise ValueError("Bu görevi KK için gönderme yetkiniz yok.")

    if not task.qc_required:
        raise ValueError("Bu görev Kalite Kontrol incelemesi gerektirmiyor.")

    with transaction.atomic():
        review = QCReview.objects.create(
            task=task,
            submitted_by=submitted_by,
            status='pending',
        )

        policy = _get_or_create_policy(QC_REVIEW_POLICY_NAME)
        snapshot = {
            'task_id': task.id,
            'task_title': task.title,
            'job_order': task.job_order_id,
            'submitted_by': submitted_by.id,
        }
        create_workflow(review, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)

    # Email QC team outside the transaction
    _email_qc_team_review_submitted(review)
    return review


def decide_qc_review(review: QCReview, user, approve: bool, comment: str = ""):
    """
    Record a QC team member's approval or rejection of a QCReview.
    On rejection, blocks the task and auto-creates a linked NCR.
    """
    with transaction.atomic():
        wf, stage, outcome = record_decision(review, user, approve, comment)

        if outcome in ('rejected', 'completed'):
            new_status = 'approved' if outcome == 'completed' else 'rejected'
            review.status = new_status
            review.reviewed_by = user
            review.reviewed_at = timezone.now()
            review.comment = comment
            review.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'comment'])

        # Side effects for rejection are triggered via handle_approval_event → _on_qc_review_rejected
        # (called inside record_decision's _notify_subject, still within this atomic block)

    return wf


def _on_qc_review_approved(review: QCReview):
    """
    Called by QCReview.handle_approval_event on 'approved' event.
    No extra DB work needed — qc_status is a computed property.
    """
    pass


def _on_qc_review_rejected(review: QCReview, comment: str = ""):
    """
    Called by QCReview.handle_approval_event on 'rejected' event (inside atomic block).
    - Blocks the task
    - Auto-creates an NCR linked to this review
    - Schedules a notification email via transaction.on_commit
    """
    task = review.task

    # Block the task
    if task.status not in ('completed', 'skipped', 'cancelled'):
        task.status = 'blocked'
        task.save(update_fields=['status'])

    # Auto-create NCR
    reviewer = review.reviewed_by or review.submitted_by
    ncr = NCR.objects.create(
        job_order=task.job_order,
        department_task=task,
        qc_review=review,
        title=f"KK Red: {task.title}",
        description=comment or "Kalite Kontrol incelemesi reddedildi.",
        defect_type='other',
        severity='minor',
        detected_by=reviewer,
        affected_quantity=1,
        disposition='pending',
        assigned_team=task.department,
        status='draft',
        created_by=reviewer,
    )

    # Link NCR back to the review
    review.ncr = ncr
    review.save(update_fields=['ncr'])

    # Send email after transaction commits (avoid email on rollback)
    from django.db import transaction as db_transaction
    db_transaction.on_commit(lambda: _email_ncr_created_on_rejection(ncr))


# =============================================================================
# NCR — submission and decision
# =============================================================================

def submit_ncr(ncr: NCR, by_user) -> None:
    """Submit an NCR for QC approval (draft → submitted)."""
    if ncr.status != 'draft':
        raise ValueError("Sadece taslak durumundaki NCR'lar gönderilebilir.")

    with transaction.atomic():
        ncr.status = 'submitted'
        ncr.save(update_fields=['status'])

        policy = _get_or_create_policy(NCR_POLICY_NAME)
        snapshot = {
            'ncr_number': ncr.ncr_number,
            'title': ncr.title,
            'severity': ncr.severity,
            'job_order': ncr.job_order_id,
        }
        create_workflow(ncr, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)

    # Email QC team outside transaction
    _email_qc_team_ncr_submitted(ncr)


def decide_ncr(ncr: NCR, user, approve: bool, comment: str = ""):
    """Record a QC team member's decision on an NCR."""
    with transaction.atomic():
        wf, stage, outcome = record_decision(ncr, user, approve, comment)

        if outcome in ('rejected', 'completed'):
            ncr.status = 'approved' if outcome == 'completed' else 'rejected'
            ncr.save(update_fields=['status'])

    return wf


def _on_ncr_approved(ncr: NCR):
    """handle_approval_event callback — status already set by decide_ncr."""
    pass


def _on_ncr_rejected(ncr: NCR, comment: str = ""):
    """handle_approval_event callback — status already set by decide_ncr."""
    pass


# =============================================================================
# Email helpers
# =============================================================================

def _email_qc_team_review_submitted(review: QCReview):
    to = _get_qc_team_emails()
    if not to:
        return
    task = review.task
    subject = f"[KK İncelemesi] {task.job_order_id} — {task.title}"
    body = (
        f"Merhaba Kalite Kontrol Ekibi,\n\n"
        f"Aşağıdaki görev KK incelemesi için gönderildi:\n\n"
        f"İş Emri: {task.job_order_id}\n"
        f"Görev: {task.title}\n"
        f"Departman: {task.get_department_display()}\n"
        f"Gönderen: {review.submitted_by.get_full_name()}\n"
        f"İnceleme ID: #{review.id}\n\n"
        f"Lütfen incelemenizi gerçekleştirin.\n\n"
        f"GEMKOM Sistemi"
    )
    send_plain_email(subject, body, to)


def _email_ncr_created_on_rejection(ncr: NCR):
    """Notify task department members when NCR is auto-created after rejection."""
    task = ncr.department_task
    if not task:
        return
    members = list(
        User.objects.filter(is_active=True, profile__team=task.department)
        .exclude(email='').exclude(email__isnull=True)
        .values_list('email', flat=True)
    )
    if not members:
        return
    subject = f"[KK Red — NCR Oluşturuldu] {ncr.ncr_number} — {task.job_order_id}"
    body = (
        f"Merhaba,\n\n"
        f"KK incelemesi reddedildi ve uygunsuzluk raporu otomatik oluşturuldu:\n\n"
        f"NCR No: {ncr.ncr_number}\n"
        f"İş Emri: {ncr.job_order_id}\n"
        f"Görev: {task.title}\n"
        f"Açıklama: {ncr.description}\n\n"
        f"Lütfen NCR'ı inceleyin ve gerekli düzeltici işlemleri gerçekleştirin.\n\n"
        f"GEMKOM Sistemi"
    )
    send_plain_email(subject, body, members)


def _email_qc_team_ncr_submitted(ncr: NCR):
    to = _get_qc_team_emails()
    if not to:
        return
    subject = f"[NCR Onay Bekliyor] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"Merhaba Kalite Kontrol Ekibi,\n\n"
        f"Aşağıdaki NCR onayınızı bekliyor:\n\n"
        f"NCR No: {ncr.ncr_number}\n"
        f"Başlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\n"
        f"Önem: {ncr.get_severity_display()}\n"
        f"Açıklama: {ncr.description}\n\n"
        f"Lütfen NCR'ı inceleyin.\n\n"
        f"GEMKOM Sistemi"
    )
    send_plain_email(subject, body, to)


def email_ncr_assigned_members(ncr: NCR):
    """Notify specific members when a manual NCR is created with assignments."""
    members_qs = ncr.assigned_members.exclude(email='').exclude(email__isnull=True)
    for member in members_qs:
        subject = f"[NCR Atandı] {ncr.ncr_number} — {ncr.title}"
        body = (
            f"Merhaba {member.get_full_name()},\n\n"
            f"Size bir Uygunsuzluk Raporu atandı:\n\n"
            f"NCR No: {ncr.ncr_number}\n"
            f"Başlık: {ncr.title}\n"
            f"İş Emri: {ncr.job_order_id}\n"
            f"Önem Derecesi: {ncr.get_severity_display()}\n"
            f"Açıklama: {ncr.description}\n\n"
            f"Lütfen NCR'ı inceleyin ve gerekli işlemleri gerçekleştirin.\n\n"
            f"GEMKOM Sistemi"
        )
        send_plain_email(subject, body, [member.email])
