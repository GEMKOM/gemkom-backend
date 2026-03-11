import threading
from django.db import transaction
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import (
    JobOrder,
    JobOrderProcurementLine,
    JobOrderQCCostLine,
    JobOrderShippingCostLine,
)
from notifications.service import notify, bulk_notify
from notifications.models import Notification


# ============================================================================
# General Expenses Rate Propagation
# ============================================================================

@receiver(pre_save, sender=JobOrder)
def capture_job_order_cost_fields(sender, instance, **kwargs):
    """Capture fields that affect cost summary before saving."""
    if instance.pk:
        try:
            old = JobOrder.objects.values(
                'general_expenses_rate', 'total_weight_kg'
            ).get(pk=instance.pk)
            instance._old_general_expenses_rate = old['general_expenses_rate']
            instance._old_total_weight_kg = old['total_weight_kg']
        except JobOrder.DoesNotExist:
            instance._old_general_expenses_rate = None
            instance._old_total_weight_kg = None
    else:
        instance._old_general_expenses_rate = None
        instance._old_total_weight_kg = None


@receiver(post_save, sender=JobOrder)
def on_job_order_cost_fields_changed(sender, instance, created, **kwargs):
    """
    - If general_expenses_rate changed: cascade to descendants, recompute all.
    - If total_weight_kg changed: recompute this job's cost summary.
    Both trigger recompute of the job itself (which chains up to parent).
    """
    if created:
        return

    rate_changed = (
        getattr(instance, '_old_general_expenses_rate', None) is not None
        and instance._old_general_expenses_rate != instance.general_expenses_rate
    )
    weight_changed = (
        getattr(instance, '_old_total_weight_kg', None) != instance.total_weight_kg
    )

    if not rate_changed and not weight_changed:
        return

    new_rate = instance.general_expenses_rate
    job_no = instance.job_no

    def _run():
        from projects.services.costing import recompute_job_cost_summary

        if rate_changed:
            def _collect(jno):
                children = list(JobOrder.objects.filter(parent_id=jno).values_list('job_no', flat=True))
                result = list(children)
                for c in children:
                    result.extend(_collect(c))
                return result

            descendants = _collect(job_no)
            if descendants:
                JobOrder.objects.filter(job_no__in=descendants).update(general_expenses_rate=new_rate)
                for djob_no in sorted(descendants):  # children before parents
                    recompute_job_cost_summary(djob_no)

        # Always recompute this job itself (chains up to parent automatically)
        recompute_job_cost_summary(job_no)

    transaction.on_commit(_run)


# ============================================================================
# Cost Summary Signals
# ============================================================================

@receiver([post_save, post_delete], sender=JobOrderProcurementLine)
@receiver([post_save, post_delete], sender=JobOrderQCCostLine)
@receiver([post_save, post_delete], sender=JobOrderShippingCostLine)
def update_job_cost_summary(sender, instance, **kwargs):
    """Recompute the job order cost summary whenever a cost line is saved or deleted."""
    from projects.services.costing import recompute_job_cost_summary
    recompute_job_cost_summary(instance.job_order_id)


# ============================================================================
# Discussion Notification Helpers
# ============================================================================

def _topic_link(topic):
    return f"https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={topic.job_order.job_no}&topic_id={topic.id}"

def _job_link(job_order):
    return f"https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}"


def send_topic_notifications(topic):
    """Send notifications to @mentioned users in a topic."""
    mentioned_users = topic.mentioned_users.exclude(id=topic.created_by_id)
    if not mentioned_users.exists():
        return
    title = f"[Etiketlendiniz] {topic.job_order.job_no} – {topic.title}"
    body = (
        f"{topic.created_by.get_full_name()} sizi bir tartisma konusunda etiketledi.\n"
        f"Is Emri: {topic.job_order.job_no} - {topic.job_order.title}\n"
        f"Konu: {topic.title}\n\n"
        f"{topic.content}"
    )
    bulk_notify(
        users=mentioned_users,
        notification_type=Notification.TOPIC_MENTION,
        title=title,
        body=body,
        link=_topic_link(topic),
        source_type='discussion_topic',
        source_id=topic.id,
    )


def send_comment_notifications(comment):
    """Send notifications to topic owner and @mentioned users."""
    topic = comment.topic

    # Notify topic owner (if someone else commented)
    if topic.created_by and topic.created_by != comment.created_by:
        title = f"[Yeni Yorum] {topic.job_order.job_no} – {topic.title}"
        body = (
            f"{comment.created_by.get_full_name()} tartisma konunuza yorum yapti.\n\n"
            f"{comment.content}"
        )
        notify(
            user=topic.created_by,
            notification_type=Notification.NEW_COMMENT,
            title=title,
            body=body,
            link=_topic_link(topic),
            source_type='discussion_topic',
            source_id=topic.id,
        )

    # Notify @mentioned users (excluding comment author and topic owner)
    exclude_ids = [comment.created_by_id]
    if topic.created_by_id:
        exclude_ids.append(topic.created_by_id)
    mentioned_users = comment.mentioned_users.exclude(id__in=exclude_ids)

    if mentioned_users.exists():
        title = f"[Yorumda Etiketlendiniz] {topic.job_order.job_no} – {topic.title}"
        body = (
            f"{comment.created_by.get_full_name()} sizi bir yorumda etiketledi.\n\n"
            f"{comment.content}"
        )
        bulk_notify(
            users=mentioned_users,
            notification_type=Notification.COMMENT_MENTION,
            title=title,
            body=body,
            link=_topic_link(topic),
            source_type='discussion_topic',
            source_id=topic.id,
        )


def send_drawing_released_notifications(release, topic):
    """Send notifications when technical drawings are released."""
    users_to_notify = topic.mentioned_users.exclude(id=release.released_by_id)
    if not users_to_notify.exists():
        return
    job_order = release.job_order
    rev = release.revision_code or release.revision_number
    title = f"[Teknik Cizim Yayinlandi] {job_order.job_no} Rev.{rev}"
    body = (
        f"{release.released_by.get_full_name()} yeni teknik cizim yayinladi.\n"
        f"Is Emri: {job_order.job_no} - {job_order.title}\n"
        f"Revizyon: {rev}\n"
        f"Hardcopy: {release.hardcopy_count} set\n\n"
        f"Klasor Yolu:\n{release.folder_path}\n\n"
        f"Degisiklikler:\n{release.changelog}"
    )
    bulk_notify(
        users=users_to_notify,
        notification_type=Notification.DRAWING_RELEASED,
        title=title,
        body=body,
        link=_topic_link(topic),
        source_type='drawing_release',
        source_id=release.id,
    )


def send_revision_requested_notifications(release, topic, requester):
    """Send notifications when a revision is requested (pending approval)."""
    job_order = release.job_order
    rev = release.revision_code or release.revision_number
    title = f"[Revizyon Talebi] {job_order.job_no} Rev.{rev}"
    body = (
        f"{requester.get_full_name()} teknik cizimler icin revizyon talep etti.\n"
        f"Is Emri: {job_order.job_no} - {job_order.title}\n"
        f"Mevcut Revizyon: {rev}\n\n"
        f"Talep Nedeni:\n{topic.content}\n\n"
        f"Bu talep onay beklemektedir."
    )

    users_to_notify = []

    # Notify design task assignee
    design_task = job_order.department_tasks.filter(
        department='design',
        parent__isnull=True
    ).first()
    if design_task and design_task.assigned_to and design_task.assigned_to != requester:
        users_to_notify.append(design_task.assigned_to)

    # Also notify the original releaser if different
    if release.released_by and release.released_by != requester:
        if not design_task or release.released_by != design_task.assigned_to:
            users_to_notify.append(release.released_by)

    for user in users_to_notify:
        notify(
            user=user,
            notification_type=Notification.REVISION_REQUESTED,
            title=title,
            body=body,
            link=_topic_link(topic),
            source_type='drawing_release',
            source_id=release.id,
        )


def send_revision_approved_notifications(release, topic, approver):
    """Send notifications when a revision is approved (job on hold)."""
    job_order = release.job_order

    # Notify the original requester
    if topic.created_by and topic.created_by != approver:
        title = f"[Revizyon Onaylandi] {job_order.job_no}"
        body = (
            f"{approver.get_full_name()} revizyon talebinizi onayladi.\n"
            f"Is Emri: {job_order.job_no} - {job_order.title}\n"
            f"Konu: {topic.title}\n\n"
            f"Is emri revizyon suresince beklemeye alinmistir."
        )
        notify(
            user=topic.created_by,
            notification_type=Notification.REVISION_APPROVED,
            title=title,
            body=body,
            link=_job_link(job_order),
            source_type='drawing_release',
            source_id=release.id,
        )

    # Notify all department task assignees (job on hold)
    send_job_on_hold_notifications(job_order, release, f"Revizyon onaylandi: {topic.title}")


def send_self_revision_notifications(release, reason, initiator):
    """Send notifications when designer self-initiates a revision."""
    job_order = release.job_order

    # Notify stakeholders from the original release topic
    if release.release_topic:
        users_to_notify = release.release_topic.mentioned_users.exclude(id=initiator.id)
        if users_to_notify.exists():
            rev = release.revision_code or release.revision_number
            title = f"[Revizyon Baslatildi] {job_order.job_no} Rev.{rev}"
            body = (
                f"{initiator.get_full_name()} teknik cizimlerde revizyon baslatti.\n"
                f"Is Emri: {job_order.job_no} - {job_order.title}\n"
                f"Mevcut Revizyon: {rev}\n\n"
                f"Neden:\n{reason}\n\n"
                f"IS EMRI BEKLEMEYE ALINDI - Revizyon tamamlanana kadar calismalar durdurulmustur."
            )
            bulk_notify(
                users=users_to_notify,
                notification_type=Notification.REVISION_REQUESTED,
                title=title,
                body=body,
                link=_job_link(job_order),
                source_type='drawing_release',
                source_id=release.id,
            )

    # Notify all department task assignees (job on hold)
    send_job_on_hold_notifications(job_order, release, reason)


def send_job_on_hold_notifications(job_order, release, reason):
    """Send notifications to all department task assignees when job is on hold."""
    from django.contrib.auth.models import User
    assignee_ids = set(
        job_order.department_tasks
        .filter(assigned_to__isnull=False)
        .values_list('assigned_to_id', flat=True)
    )
    if not assignee_ids:
        return
    assignees = User.objects.filter(id__in=assignee_ids, is_active=True)
    title = f"[Is Emri Beklemede] {job_order.job_no}"
    body = (
        f"{job_order.job_no} numarali is emri revizyon nedeniyle bekletilmistir.\n"
        f"Revizyon tamamlanana kadar bu is emri uzerindeki calismalara devam etmeyiniz.\n\n"
        f"Neden: {reason}"
    )
    bulk_notify(
        users=assignees,
        notification_type=Notification.JOB_ON_HOLD,
        title=title,
        body=body,
        link=_job_link(job_order),
        source_type='job_order',
        source_id=job_order.id,
    )


def send_revision_completed_notifications(new_release, new_topic, old_revision_topic, completer):
    """Send notifications when revision is completed and new release is made."""
    job_order = new_release.job_order
    rev = new_release.revision_code or new_release.revision_number
    title = f"[Revizyon Tamamlandi] {job_order.job_no} Rev.{rev}"
    body = (
        f"{completer.get_full_name()} revizyonu tamamladi ve yeni cizim yayinladi.\n"
        f"Is Emri: {job_order.job_no} - {job_order.title}\n"
        f"Yeni Revizyon: {rev}\n\n"
        f"Degisiklikler:\n{new_release.changelog}\n\n"
        f"Klasor Yolu:\n{new_release.folder_path}\n\n"
        f"Is emri devam etmektedir."
    )

    # Notify the original revision requester
    if old_revision_topic and old_revision_topic.created_by and old_revision_topic.created_by != completer:
        notify(
            user=old_revision_topic.created_by,
            notification_type=Notification.REVISION_COMPLETED,
            title=title,
            body=body,
            link=_topic_link(new_topic),
            source_type='drawing_release',
            source_id=new_release.id,
        )

    # Notify mentioned users in the new topic
    users_to_notify = new_topic.mentioned_users.exclude(id=completer.id)
    if old_revision_topic and old_revision_topic.created_by:
        users_to_notify = users_to_notify.exclude(id=old_revision_topic.created_by.id)
    if users_to_notify.exists():
        bulk_notify(
            users=users_to_notify,
            notification_type=Notification.DRAWING_RELEASED,
            title=title,
            body=body,
            link=_topic_link(new_topic),
            source_type='drawing_release',
            source_id=new_release.id,
        )

    # Notify all department task assignees (job resumed)
    send_job_resumed_notifications(job_order, new_topic, new_release)


def send_job_resumed_notifications(job_order, topic, release):
    """Send notifications to all department task assignees when job is resumed."""
    from django.contrib.auth.models import User
    assignee_ids = set(
        job_order.department_tasks
        .filter(assigned_to__isnull=False)
        .values_list('assigned_to_id', flat=True)
    )
    if not assignee_ids:
        return
    assignees = User.objects.filter(id__in=assignee_ids, is_active=True)
    rev = release.revision_code or release.revision_number
    title = f"[Is Emri Devam Ediyor] {job_order.job_no}"
    body = (
        f"{job_order.job_no} numarali is emri uzerindeki revizyon tamamlanmistir.\n"
        f"Calismalara devam edebilirsiniz.\n\n"
        f"Yeni Revizyon: {rev}"
    )
    bulk_notify(
        users=assignees,
        notification_type=Notification.JOB_RESUMED,
        title=title,
        body=body,
        link=_job_link(job_order),
        source_type='job_order',
        source_id=job_order.id,
    )


def send_revision_rejected_notifications(release, topic, reason, rejecter):
    """Send notification when a revision request is rejected."""
    if not topic.created_by or topic.created_by == rejecter:
        return
    job_order = release.job_order
    rev = release.revision_code or release.revision_number
    title = f"[Revizyon Talebi Reddedildi] {job_order.job_no} Rev.{rev}"
    body = (
        f"{rejecter.get_full_name()} revizyon talebinizi reddetti.\n"
        f"Is Emri: {job_order.job_no} - {job_order.title}\n"
        f"Konu: {topic.title}\n\n"
        f"Red Nedeni:\n{reason}"
    )
    notify(
        user=topic.created_by,
        notification_type=Notification.REVISION_REJECTED,
        title=title,
        body=body,
        link=_topic_link(topic),
        source_type='drawing_release',
        source_id=release.id,
    )
