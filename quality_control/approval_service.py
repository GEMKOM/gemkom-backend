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

def submit_for_qc_review(task, submitted_by, part_data: dict | None = None) -> QCReview:
    """
    Submit a manufacturing task for QC review.
    Creates a QCReview and an ApprovalWorkflow targeting the QC team.

    Permission: submitted_by must belong to the task's department or qualitycontrol.
    part_data: optional free-form JSON (location, quantity, drawing no, position no, etc.)
    """
    if not task.qc_required:
        raise ValueError("Bu görev KK incelemesine uygun değil. Yalnızca imalat ana görevleri ve parça görevleri KK incelemesine gönderilebilir.")

    user_team = getattr(getattr(submitted_by, 'profile', None), 'team', None)
    if user_team not in (task.department, 'qualitycontrol') and not submitted_by.is_superuser:
        raise ValueError("Bu görevi KK için gönderme yetkiniz yok.")

    with transaction.atomic():
        review = QCReview.objects.create(
            task=task,
            submitted_by=submitted_by,
            status='pending',
            part_data=part_data or {},
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


def bulk_submit_for_qc_review(task, submitted_by, part_data_list: list[dict]) -> list[QCReview]:
    """
    Create multiple QCReviews for a single task in one atomic block.
    Each item in part_data_list becomes one review with its own part_data.
    A single notification email is sent to the QC team after the transaction.

    Permission: same as submit_for_qc_review — submitted_by must belong to
    the task's department or qualitycontrol team (or be a superuser).
    """
    if not task.qc_required:
        raise ValueError("Bu görev KK incelemesine uygun değil. Yalnızca imalat ana görevleri ve parça görevleri KK incelemesine gönderilebilir.")

    user_team = getattr(getattr(submitted_by, 'profile', None), 'team', None)
    if user_team not in (task.department, 'qualitycontrol') and not submitted_by.is_superuser:
        raise ValueError("Bu görevi KK için gönderme yetkiniz yok.")

    policy = _get_or_create_policy(QC_REVIEW_POLICY_NAME)
    reviews = []

    with transaction.atomic():
        for part_data in part_data_list:
            review = QCReview.objects.create(
                task=task,
                submitted_by=submitted_by,
                status='pending',
                part_data=part_data or {},
            )
            snapshot = {
                'task_id': task.id,
                'task_title': task.title,
                'job_order': task.job_order_id,
                'submitted_by': submitted_by.id,
            }
            create_workflow(review, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)
            reviews.append(review)

    # Single email for the entire batch
    _email_qc_team_bulk_reviews_submitted(reviews, task, submitted_by)
    return reviews


def decide_qc_review(review: QCReview, user, approve: bool, comment: str = "", ncr_data: dict | None = None):
    """
    Record a QC team member's approval or rejection of a QCReview.
    On rejection, blocks the task and auto-creates a linked NCR prefilled with ncr_data.
    ncr_data keys: title, description, defect_type, severity, affected_quantity, disposition
    """
    review._ncr_prefill = ncr_data or {}

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

    # Auto-create NCR, prefilled with any data passed via _ncr_prefill
    reviewer = review.reviewed_by or review.submitted_by
    prefill = getattr(review, '_ncr_prefill', {})
    ncr = NCR.objects.create(
        job_order=task.job_order,
        department_task=task,
        qc_review=review,
        title=prefill.get('title') or f"KK Red: {task.title}",
        description=prefill.get('description') or comment or "Kalite Kontrol incelemesi reddedildi.",
        defect_type=prefill.get('defect_type') or 'other',
        severity=prefill.get('severity') or 'minor',
        detected_by=reviewer,
        affected_quantity=prefill.get('affected_quantity') or 1,
        disposition=prefill.get('disposition') or 'pending',
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

def submit_ncr(ncr: NCR, by_user, field_updates: dict | None = None) -> None:
    """
    Submit (or resubmit) an NCR for QC approval.
    Allowed from: draft, rejected.
    submission_count is incremented on every submission.
    A fresh ApprovalWorkflow is created each time.

    field_updates: optional dict of NCR fields to save atomically before submission
    (e.g. root_cause, corrective_action, disposition, assigned_members, etc.)
    M2M fields (assigned_members) are handled separately after the save.
    """
    if ncr.status not in ('draft', 'rejected'):
        raise ValueError("Sadece taslak veya reddedilmiş NCR'lar gönderilebilir.")

    with transaction.atomic():
        update_fields = ['status', 'submission_count']
        m2m_updates = {}

        if field_updates:
            m2m_fields = {'assigned_members'}
            for field, value in field_updates.items():
                if field in m2m_fields:
                    m2m_updates[field] = value
                else:
                    setattr(ncr, field, value)
                    update_fields.append(field)

        ncr.status = 'submitted'
        ncr.submission_count += 1
        ncr.save(update_fields=update_fields)

        for field, value in m2m_updates.items():
            getattr(ncr, field).set(value)

        policy = _get_or_create_policy(NCR_POLICY_NAME)
        snapshot = {
            'ncr_number': ncr.ncr_number,
            'title': ncr.title,
            'severity': ncr.severity,
            'job_order': ncr.job_order_id,
            'submission_count': ncr.submission_count,
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
    """
    Called by NCR.handle_approval_event on 'approved' event (inside atomic block).
    Unblocks the linked task so work can resume after the NCR is resolved.
    """
    task = ncr.department_task
    if task and task.status == 'blocked':
        task.status = 'in_progress'
        task.save(update_fields=['status'])


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


def _email_qc_team_bulk_reviews_submitted(reviews: list, task, submitted_by):
    to = _get_qc_team_emails()
    if not to:
        return
    count = len(reviews)
    review_ids = ", ".join(f"#{r.id}" for r in reviews)
    subject = f"[KK İncelemesi] {task.job_order_id} — {task.title} ({count} inceleme)"
    body = (
        f"Merhaba Kalite Kontrol Ekibi,\n\n"
        f"Aşağıdaki görev için {count} adet KK incelemesi gönderildi:\n\n"
        f"İş Emri: {task.job_order_id}\n"
        f"Görev: {task.title}\n"
        f"Departman: {task.get_department_display()}\n"
        f"Gönderen: {submitted_by.get_full_name()}\n"
        f"İnceleme ID'leri: {review_ids}\n\n"
        f"Lütfen incelemeleri gerçekleştirin.\n\n"
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
