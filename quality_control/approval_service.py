from __future__ import annotations

from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone

from approvals.services import create_workflow, record_decision
from approvals.models import ApprovalPolicy, ApprovalStage

from .models import QCReview, NCR

from notifications.service import notify, bulk_notify
from notifications.models import Notification


QC_REVIEW_POLICY_NAME = "KK İnceleme Onay Politikası"
NCR_POLICY_NAME = "NCR Onay Politikası"


def _get_qc_team_users():
    return User.objects.filter(is_active=True, profile__team='qualitycontrol')


def _get_qc_team_user_ids() -> list[int]:
    return list(_get_qc_team_users().values_list('id', flat=True))


def _get_or_create_policy(policy_name: str) -> ApprovalPolicy:
    policy, created = ApprovalPolicy.objects.get_or_create(
        name=policy_name,
        defaults={'is_active': True}
    )
    if created:
        ApprovalStage.objects.create(
            policy=policy, order=1,
            name='Kalite Kontrol Onayı',
            required_approvals=1,
        )
    return policy


def _qc_team_builder(stage, _subject):
    return _get_qc_team_user_ids(), []


# =============================================================================
# QCReview
# =============================================================================

def submit_for_qc_review(task, submitted_by, part_data=None) -> QCReview:
    if not task.qc_required:
        raise ValueError(
            "Bu görev KK incelemesine uygun değil. Yalnızca imalat ana görevleri ve "
            "parça görevleri KK incelemesine gönderilebilir."
        )
    user_team = getattr(getattr(submitted_by, 'profile', None), 'team', None)
    if user_team not in (task.department, 'qualitycontrol') and not submitted_by.is_superuser:
        raise ValueError("Bu görevi KK için gönderme yetkiniz yok.")

    with transaction.atomic():
        review = QCReview.objects.create(
            task=task, submitted_by=submitted_by,
            status='pending', part_data=part_data or {},
        )
        policy = _get_or_create_policy(QC_REVIEW_POLICY_NAME)
        snapshot = {
            'task_id': task.id, 'task_title': task.title,
            'job_order': task.job_order_id, 'submitted_by': submitted_by.id,
        }
        create_workflow(review, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)

    _notify_qc_team_review_submitted(review)
    return review


def bulk_submit_for_qc_review(task, submitted_by, part_data_list: list) -> list:
    if not task.qc_required:
        raise ValueError(
            "Bu görev KK incelemesine uygun değil. Yalnızca imalat ana görevleri ve "
            "parça görevleri KK incelemesine gönderilebilir."
        )
    user_team = getattr(getattr(submitted_by, 'profile', None), 'team', None)
    if user_team not in (task.department, 'qualitycontrol') and not submitted_by.is_superuser:
        raise ValueError("Bu görevi KK için gönderme yetkiniz yok.")

    policy = _get_or_create_policy(QC_REVIEW_POLICY_NAME)
    reviews = []

    with transaction.atomic():
        for part_data in part_data_list:
            review = QCReview.objects.create(
                task=task, submitted_by=submitted_by,
                status='pending', part_data=part_data or {},
            )
            snapshot = {
                'task_id': task.id, 'task_title': task.title,
                'job_order': task.job_order_id, 'submitted_by': submitted_by.id,
            }
            create_workflow(review, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)
            reviews.append(review)

    _notify_qc_team_bulk_reviews_submitted(reviews, task, submitted_by)
    return reviews


def decide_qc_review(review: QCReview, user, approve: bool, comment: str = "", ncr_data=None):
    review._ncr_prefill = ncr_data or {}

    with transaction.atomic():
        wf, stage, outcome = record_decision(review, user, approve, comment)

        if outcome in ('rejected', 'completed'):
            review.status = 'approved' if outcome == 'completed' else 'rejected'
            review.reviewed_by = user
            review.reviewed_at = timezone.now()
            review.comment = comment
            review.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'comment'])

    return wf


def _on_qc_review_approved(review: QCReview):
    from django.db import transaction as db_tx
    db_tx.on_commit(lambda: _notify_review_approved(review))


def _on_qc_review_rejected(review: QCReview, comment: str = ""):
    task = review.task
    if task.status not in ('completed', 'skipped', 'cancelled'):
        task.status = 'blocked'
        task.save(update_fields=['status'])

    reviewer = review.reviewed_by or review.submitted_by
    prefill = getattr(review, '_ncr_prefill', {})
    ncr = NCR.objects.create(
        job_order=task.job_order, department_task=task, qc_review=review,
        title=prefill.get('title') or f"KK Red: {task.title}",
        description=prefill.get('description') or comment or "Kalite Kontrol incelemesi reddedildi.",
        defect_type=prefill.get('defect_type') or 'other',
        severity=prefill.get('severity') or 'minor',
        detected_by=reviewer,
        affected_quantity=prefill.get('affected_quantity') or 1,
        disposition=prefill.get('disposition') or 'pending',
        assigned_team=task.department, status='draft', created_by=reviewer,
    )
    review.ncr = ncr
    review.save(update_fields=['ncr'])

    from django.db import transaction as db_tx
    db_tx.on_commit(lambda: _notify_ncr_created_on_rejection(ncr))
    db_tx.on_commit(lambda: _notify_review_rejected(review))


# =============================================================================
# NCR
# =============================================================================

def submit_ncr(ncr: NCR, by_user, field_updates=None) -> None:
    if ncr.status not in ('draft', 'rejected'):
        raise ValueError("Sadece taslak veya reddedilmiş NCR'lar gönderilebilir.")

    with transaction.atomic():
        update_fields = ['status', 'submission_count']
        m2m_updates = {}
        if field_updates:
            for field, value in field_updates.items():
                if field == 'assigned_members':
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
            'ncr_number': ncr.ncr_number, 'title': ncr.title,
            'severity': ncr.severity, 'job_order': ncr.job_order_id,
            'submission_count': ncr.submission_count,
        }
        create_workflow(ncr, policy, snapshot=snapshot, approver_user_ids_builder=_qc_team_builder)

    _notify_qc_team_ncr_submitted(ncr)


def decide_ncr(ncr: NCR, user, approve: bool, comment: str = ""):
    with transaction.atomic():
        wf, stage, outcome = record_decision(ncr, user, approve, comment)
        if outcome in ('rejected', 'completed'):
            ncr.status = 'approved' if outcome == 'completed' else 'rejected'
            ncr.save(update_fields=['status'])
    return wf


def _on_ncr_approved(ncr: NCR):
    task = ncr.department_task
    if task and task.status == 'blocked':
        task.status = 'in_progress'
        task.save(update_fields=['status'])
    from django.db import transaction as db_tx
    db_tx.on_commit(lambda: _notify_ncr_approved(ncr))


def _on_ncr_rejected(ncr: NCR, comment: str = ""):
    from django.db import transaction as db_tx
    db_tx.on_commit(lambda: _notify_ncr_rejected(ncr, comment))


# =============================================================================
# Notification helpers
# =============================================================================

def _notify_qc_team_review_submitted(review: QCReview):
    qc_users = _get_qc_team_users()
    if not qc_users.exists():
        return
    task = review.task
    title = f"[KK İncelemesi] {task.job_order_id} — {task.title}"
    body = (
        f"Görev KK incelemesi için gönderildi.\n\n"
        f"İş Emri: {task.job_order_id}\nGörev: {task.title}\n"
        f"Departman: {task.get_department_display()}\nGönderen: {review.submitted_by.get_full_name()}\n"
        f"İnceleme ID: #{review.id}"
    )
    bulk_notify(users=qc_users, notification_type=Notification.QC_REVIEW_SUBMITTED,
                title=title, body=body, source_type='qc_review', source_id=review.id)


def _notify_qc_team_bulk_reviews_submitted(reviews: list, task, submitted_by):
    qc_users = _get_qc_team_users()
    if not qc_users.exists():
        return
    count = len(reviews)
    review_ids = ", ".join(f"#{r.id}" for r in reviews)
    title = f"[KK İncelemesi] {task.job_order_id} — {task.title} ({count} inceleme)"
    body = (
        f"{task.job_order_id} / {task.title} için {count} adet KK incelemesi gönderildi.\n"
        f"Gönderen: {submitted_by.get_full_name()}\nİnceleme ID'leri: {review_ids}"
    )
    bulk_notify(users=qc_users, notification_type=Notification.QC_REVIEW_SUBMITTED,
                title=title, body=body, source_type='qc_review',
                source_id=reviews[0].id if reviews else None)


def _notify_review_approved(review: QCReview):
    task = review.task
    recipients = {review.submitted_by}
    recipients.update(User.objects.filter(is_active=True, profile__team=task.department))
    title = f"[KK Onaylandı] {task.job_order_id} — {task.title}"
    body = (
        f"İş Emri {task.job_order_id} / Görev: {task.title} KK incelemesi onaylandı.\n"
        f"İnceleme ID: #{review.id}"
    )
    bulk_notify(users=list(recipients), notification_type=Notification.QC_REVIEW_APPROVED,
                title=title, body=body, source_type='qc_review', source_id=review.id)


def _notify_review_rejected(review: QCReview):
    task = review.task
    title = f"[KK Reddedildi] {task.job_order_id} — {task.title}"
    body = (
        f"Gönderdiğiniz KK incelemesi reddedildi.\n\n"
        f"İş Emri: {task.job_order_id}\nGörev: {task.title}\n"
        f"İnceleme ID: #{review.id}\nYorum: {review.comment or chr(8212)}\n\n"
        f"Otomatik NCR oluşturuldu."
    )
    notify(user=review.submitted_by, notification_type=Notification.QC_REVIEW_REJECTED,
           title=title, body=body, source_type='qc_review', source_id=review.id)


def _notify_ncr_created_on_rejection(ncr: NCR):
    task = ncr.department_task
    if not task:
        return
    dept_users = User.objects.filter(is_active=True, profile__team=task.department)
    if not dept_users.exists():
        return
    title = f"[KK Red — NCR Oluşturuldu] {ncr.ncr_number} — {task.job_order_id}"
    body = (
        f"KK incelemesi reddedildi ve NCR otomatik oluşturuldu.\n\n"
        f"NCR No: {ncr.ncr_number}\nİş Emri: {ncr.job_order_id}\n"
        f"Görev: {task.title}\nAçıklama: {ncr.description}"
    )
    bulk_notify(users=dept_users, notification_type=Notification.NCR_CREATED,
                title=title, body=body, source_type='ncr', source_id=ncr.id)


def _notify_qc_team_ncr_submitted(ncr: NCR):
    qc_users = _get_qc_team_users()
    if not qc_users.exists():
        return
    title = f"[NCR Onay Bekliyor] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"NCR onayınızı bekliyor.\n\nNCR No: {ncr.ncr_number}\nBaşlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\nÖnem: {ncr.get_severity_display()}\nAçıklama: {ncr.description}"
    )
    bulk_notify(users=qc_users, notification_type=Notification.NCR_SUBMITTED,
                title=title, body=body, source_type='ncr', source_id=ncr.id)


def _notify_ncr_approved(ncr: NCR):
    recipients = set()
    if ncr.created_by:
        recipients.add(ncr.created_by)
    recipients.update(ncr.assigned_members.filter(is_active=True))
    if ncr.department_task:
        recipients.update(User.objects.filter(is_active=True, profile__team=ncr.department_task.department))
    if not recipients:
        return
    title = f"[NCR Onaylandı] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"NCR onaylandı.\n\nNCR No: {ncr.ncr_number}\nBaşlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\nÖnem: {ncr.get_severity_display()}"
    )
    bulk_notify(users=list(recipients), notification_type=Notification.NCR_APPROVED,
                title=title, body=body, source_type='ncr', source_id=ncr.id)


def _notify_ncr_rejected(ncr: NCR, comment: str = ""):
    if not ncr.created_by:
        return
    title = f"[NCR Reddedildi] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"NCR reddedildi.\n\nNCR No: {ncr.ncr_number}\nBaşlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\nYorum: {comment or chr(8212)}\n\n"
        f"Lütfen NCR'ı güncelleyip yeniden gönderin."
    )
    notify(user=ncr.created_by, notification_type=Notification.NCR_REJECTED,
           title=title, body=body, source_type='ncr', source_id=ncr.id)


def email_ncr_assigned_team(ncr: NCR):
    if not ncr.assigned_team:
        return
    dept_users = User.objects.filter(is_active=True, profile__team=ncr.assigned_team)
    if not dept_users.exists():
        return
    title = f"[Yeni NCR] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"Departmanınız için yeni NCR.\n\nNCR No: {ncr.ncr_number}\nBaşlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\nÖnem: {ncr.get_severity_display()}\nAçıklama: {ncr.description}"
    )
    bulk_notify(users=dept_users, notification_type=Notification.NCR_CREATED,
                title=title, body=body, source_type='ncr', source_id=ncr.id)


def email_ncr_assigned_members(ncr: NCR):
    members = list(ncr.assigned_members.filter(is_active=True))
    if not members:
        return
    title = f"[NCR Atandı] {ncr.ncr_number} — {ncr.title}"
    body = (
        f"Size bir NCR atandı.\n\nNCR No: {ncr.ncr_number}\nBaşlık: {ncr.title}\n"
        f"İş Emri: {ncr.job_order_id}\nÖnem: {ncr.get_severity_display()}\nAçıklama: {ncr.description}"
    )
    bulk_notify(users=members, notification_type=Notification.NCR_ASSIGNED,
                title=title, body=body, source_type='ncr', source_id=ncr.id)
