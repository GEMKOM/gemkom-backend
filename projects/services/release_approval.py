"""Peer-review approval workflow for technical drawing releases."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.db.models import Min

from organization.models import Position

User = get_user_model()

REQUIRED_APPROVAL_COUNT = 2


def get_design_department_users():
    """Active users in the design department."""
    return User.objects.filter(
        is_active=True,
        profile__position__department_code='design',
        profile__position__is_active=True,
    ).distinct()


def get_design_lead_user_ids():
    """User IDs of design department members at the highest authority level."""
    min_level = Position.objects.filter(
        department_code='design',
        is_active=True,
        holders__user__is_active=True,
    ).aggregate(min_level=Min('level'))['min_level']
    if min_level is None:
        return set()
    return set(
        User.objects.filter(
            is_active=True,
            profile__position__department_code='design',
            profile__position__level=min_level,
            profile__position__is_active=True,
        ).values_list('id', flat=True)
    )


def is_design_department_member(user):
    if not user or not user.is_active:
        return False
    return get_design_department_users().filter(pk=user.pk).exists()


def get_approved_approver_ids(release):
    return list(
        release.approvals.filter(decision='approved').values_list('approver_id', flat=True)
    )


def approval_requirements_met(release):
    """
  2 distinct approvals from design members (creator excluded).
  At least one must be a department lead, unless the creator is a lead —
  then any two other design members suffice.
    """
    creator_id = release.released_by_id
    lead_ids = get_design_lead_user_ids()
    design_ids = set(get_design_department_users().values_list('id', flat=True))

    valid_approvers = [
        uid for uid in get_approved_approver_ids(release)
        if uid != creator_id and uid in design_ids
    ]
    if len(valid_approvers) < REQUIRED_APPROVAL_COUNT:
        return False

    if creator_id in lead_ids:
        return True

    return any(uid in lead_ids for uid in valid_approvers)


def get_approval_state(release):
    """Summary of approval progress for API consumers."""
    creator_id = release.released_by_id
    lead_ids = get_design_lead_user_ids()
    design_ids = set(get_design_department_users().values_list('id', flat=True))
    approved_ids = [
        uid for uid in get_approved_approver_ids(release)
        if uid != creator_id and uid in design_ids
    ]
    has_lead_approval = any(uid in lead_ids for uid in approved_ids)
    creator_is_lead = creator_id in lead_ids

    return {
        'approval_count': len(approved_ids),
        'required_count': REQUIRED_APPROVAL_COUNT,
        'has_lead_approval': has_lead_approval,
        'creator_is_lead': creator_is_lead,
        'requirements_met': approval_requirements_met(release),
    }


def user_can_approve(release, user):
    if release.status != 'pending_approval':
        return False
    if not user or not user.is_active:
        return False
    if release.released_by_id == user.id:
        return False
    if not is_design_department_member(user):
        return False
    return not release.approvals.filter(approver=user).exists()


def user_can_resubmit(release, user):
    return (
        release.status == 'rejected'
        and user
        and user.is_active
        and release.released_by_id == user.id
    )


def job_has_blocking_release_review(job_order):
    """
    Revision releases keep the job on hold until the replacement drawing is approved.
    """
    from projects.models import TechnicalDrawingRelease

    return TechnicalDrawingRelease.objects.filter(job_order=job_order).filter(
        Q(status='in_revision') |
        Q(status='pending_approval', supersedes__isnull=False)
    ).exists()


def create_pending_release_topic(release, topic_content=''):
    """Create a discussion topic for a pending release (design-only visibility)."""
    from projects.models import JobOrderDiscussionTopic

    job_order = release.job_order
    rev = release.revision_code or release.revision_number
    topic_title = f'Teknik Çizim Yayını (İnceleme Bekliyor) - Rev.{rev}'

    if topic_content:
        content = topic_content
    else:
        creator_name = release.released_by.get_full_name() if release.released_by else 'Bilinmeyen'
        content = f"""{creator_name} yeni teknik çizim yayını oluşturdu (inceleme bekliyor):

İş Emri: {job_order.job_no} - {job_order.title}
Revizyon: {rev}
Hardcopy: {release.hardcopy_count} set planlama birimine bırakılacaktır.

Klasör Yolu:
{release.folder_path}

Değişiklikler:
{release.changelog}

Bu yayın tasarım ekibi incelemesi beklemektedir (en az 2 değerlendirme gerekli)."""

    topic = JobOrderDiscussionTopic.objects.create(
        job_order=job_order,
        title=topic_title,
        content=content,
        priority='normal',
        topic_type='release_review',
        created_by=release.released_by,
    )

    mentioned_users_from_content = topic.extract_mentions()
    design_users = get_design_department_users()
    all_mentioned_ids = set(design_users.values_list('id', flat=True))
    if mentioned_users_from_content.exists():
        all_mentioned_ids.update(mentioned_users_from_content.values_list('id', flat=True))
    if release.released_by_id:
        all_mentioned_ids.discard(release.released_by_id)
    if all_mentioned_ids:
        topic.mentioned_users.set(all_mentioned_ids)

    release.release_topic = topic
    release.save(update_fields=['release_topic'])
    return topic


def publish_release(release, final_approver=None):
    """
    Finalize a pending release: notify stakeholders, complete design task,
    and handle revision supersede + job resume when applicable.
    """
    from projects.models import JobOrderDiscussionTopic
    from projects.serializers import get_drawing_release_stakeholders
    from projects.signals import (
        send_drawing_released_notifications,
        send_revision_completed_notifications,
    )

    if release.status != 'pending_approval':
        raise ValueError('Sadece inceleme bekleyen yayınlar yayınlanabilir.')

    actor = final_approver or release.released_by
    job_order = release.job_order
    topic = release.release_topic

    if release.supersedes_id and job_order.status not in ('on_hold', 'active'):
        raise ValueError('Revizyon yayını yalnızca aktif veya beklemedeki iş emirlerinde yayınlanabilir.')

    with transaction.atomic():
        release.status = 'released'
        release.save(update_fields=['status', 'updated_at'])

        if topic:
            topic.title = (
                f'Teknik Çizim Yayını - Rev.{release.revision_code or release.revision_number}'
            )
            topic.topic_type = 'drawing_release'
            topic.save(update_fields=['title', 'topic_type', 'updated_at'])

            stakeholder_users = get_drawing_release_stakeholders()
            mentioned_ids = set(topic.mentioned_users.values_list('id', flat=True))
            mentioned_ids.update(stakeholder_users.values_list('id', flat=True))
            if release.released_by_id:
                mentioned_ids.discard(release.released_by_id)
            if mentioned_ids:
                topic.mentioned_users.set(mentioned_ids)

            send_drawing_released_notifications(release, topic)

        old_revision_topic = None
        if release.supersedes_id:
            old_release = release.supersedes
            old_release.status = 'superseded'
            old_release.save(update_fields=['status', 'updated_at'])

            old_revision_topic = old_release.revision_topics.filter(
                revision_status='in_progress',
                is_deleted=False,
            ).first()
            if old_revision_topic:
                old_revision_topic.revision_status = 'resolved'
                old_revision_topic.save(update_fields=['revision_status', 'updated_at'])

            if job_order.status == 'on_hold':
                job_order.resume()

            if release.auto_complete_design_task:
                design_task = job_order.department_tasks.filter(
                    department='design',
                    parent__isnull=True,
                ).first()
                if design_task and design_task.status == 'in_progress':
                    design_task.complete(user=actor)

            if topic:
                send_revision_completed_notifications(
                    release, topic, old_revision_topic, actor
                )
        elif release.auto_complete_design_task:
            design_task = job_order.department_tasks.filter(
                department='design',
                parent__isnull=True,
            ).first()
            if design_task and design_task.status == 'in_progress':
                design_task.complete(user=actor)

    return release
