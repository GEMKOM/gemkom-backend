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
from notifications.service import notify, bulk_notify, get_route, render_notification
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

def send_topic_notifications(topic):
    """Send notifications to @mentioned users in a topic."""
    mentioned_users = topic.mentioned_users.exclude(id=topic.created_by_id)
    if not mentioned_users.exists():
        return
    ctx = {
        'actor':         topic.created_by.get_full_name(),
        'job_no':        topic.job_order.job_no,
        'job_title':     topic.job_order.title,
        'topic_title':   topic.title,
        'topic_content': topic.content,
        'topic_id':      topic.id,
    }
    title, body, link = render_notification(Notification.TOPIC_MENTION, ctx)
    bulk_notify(
        users=mentioned_users,
        notification_type=Notification.TOPIC_MENTION,
        title=title,
        body=body,
        link=link,
        source_type='discussion_topic',
        source_id=topic.id,
    )


def send_comment_notifications(comment):
    """Send notifications to topic owner, task participants, and @mentioned users."""
    topic = comment.topic
    job_no = topic.job_order.job_no if topic.job_order_id else f'Task-{topic.task_id}'

    # Collect users to notify about new comment (topic creator + task assignee, excluding commenter)
    users_to_notify_new_comment = set()
    if topic.created_by and topic.created_by != comment.created_by:
        users_to_notify_new_comment.add(topic.created_by)
    if topic.task_id:
        task = topic.task
        if task.assigned_to and task.assigned_to != comment.created_by:
            users_to_notify_new_comment.add(task.assigned_to)
        if task.created_by and task.created_by != comment.created_by:
            users_to_notify_new_comment.add(task.created_by)

    if users_to_notify_new_comment:
        ctx = {
            'actor':           comment.created_by.get_full_name(),
            'job_no':          job_no,
            'topic_title':     topic.title,
            'comment_content': comment.content,
            'topic_id':        topic.id,
        }
        title, body, link = render_notification(Notification.NEW_COMMENT, ctx)
        for user in users_to_notify_new_comment:
            notify(
                user=user,
                notification_type=Notification.NEW_COMMENT,
                title=title,
                body=body,
                link=link,
                source_type='discussion_topic',
                source_id=topic.id,
            )

    # Notify @mentioned users (excluding comment author and already-notified users)
    exclude_ids = {comment.created_by_id} | {u.id for u in users_to_notify_new_comment}
    mentioned_users = comment.mentioned_users.exclude(id__in=exclude_ids)

    if mentioned_users.exists():
        ctx = {
            'actor':           comment.created_by.get_full_name(),
            'job_no':          job_no,
            'topic_title':     topic.title,
            'comment_content': comment.content,
            'topic_id':        topic.id,
        }
        title, body, link = render_notification(Notification.COMMENT_MENTION, ctx)
        bulk_notify(
            users=mentioned_users,
            notification_type=Notification.COMMENT_MENTION,
            title=title,
            body=body,
            link=link,
            source_type='discussion_topic',
            source_id=topic.id,
        )


def send_drawing_released_notifications(release, topic):
    """Send notifications when technical drawings are released."""
    job_order = release.job_order
    rev = release.revision_code or release.revision_number

    # Route-configured users
    route_users, route_link = get_route(Notification.DRAWING_RELEASED)
    exclude_id = release.released_by_id

    # Merge: topic mentioned users + route users, excluding releaser
    from django.contrib.auth.models import User
    mentioned_ids = set(topic.mentioned_users.exclude(id=exclude_id).values_list('id', flat=True))
    route_ids = set(route_users.exclude(id=exclude_id).values_list('id', flat=True))
    all_ids = mentioned_ids | route_ids
    if not all_ids:
        return

    ctx = {
        'actor':          release.released_by.get_full_name(),
        'job_no':         job_order.job_no,
        'job_title':      job_order.title,
        'revision':       rev,
        'hardcopy_count': release.hardcopy_count,
        'folder_path':    release.folder_path,
        'changelog':      release.changelog,
        'topic_id':       topic.id,
    }
    title, body, link = render_notification(Notification.DRAWING_RELEASED, ctx, route_link)
    users_to_notify = User.objects.filter(id__in=all_ids)
    bulk_notify(
        users=users_to_notify,
        notification_type=Notification.DRAWING_RELEASED,
        title=title,
        body=body,
        link=link,
        source_type='drawing_release',
        source_id=release.id,
    )


def send_revision_requested_notifications(release, topic, requester):
    """Send notifications when a revision is requested (pending approval)."""
    job_order = release.job_order
    rev = release.revision_code or release.revision_number

    user_ids = set()

    # Design task assignee
    design_task = job_order.department_tasks.filter(
        department='design',
        parent__isnull=True
    ).first()
    if design_task and design_task.assigned_to and design_task.assigned_to != requester:
        user_ids.add(design_task.assigned_to_id)

    # Original releaser if different
    if release.released_by and release.released_by != requester:
        if not design_task or release.released_by != design_task.assigned_to:
            user_ids.add(release.released_by_id)

    # Route-configured users
    route_users, route_link = get_route(Notification.REVISION_REQUESTED)
    route_ids = set(route_users.exclude(id=requester.id).values_list('id', flat=True))
    user_ids |= route_ids

    ctx = {
        'actor':         requester.get_full_name(),
        'job_no':        job_order.job_no,
        'job_title':     job_order.title,
        'revision':      rev,
        'topic_content': topic.content,
        'topic_id':      topic.id,
    }
    title, body, link = render_notification(Notification.REVISION_REQUESTED, ctx, route_link)

    from django.contrib.auth.models import User
    for user in User.objects.filter(id__in=user_ids):
        notify(
            user=user,
            notification_type=Notification.REVISION_REQUESTED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=release.id,
        )


def send_revision_approved_notifications(release, topic, approver):
    """Send notifications when a revision is approved (job on hold)."""
    job_order = release.job_order

    ctx = {
        'actor':       approver.get_full_name(),
        'job_no':      job_order.job_no,
        'job_title':   job_order.title,
        'topic_title': topic.title,
        'topic_id':    topic.id,
    }

    # Notify the original requester
    if topic.created_by and topic.created_by != approver:
        title, body, link = render_notification(Notification.REVISION_APPROVED, ctx)
        notify(
            user=topic.created_by,
            notification_type=Notification.REVISION_APPROVED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=release.id,
        )

    # Route-configured users (excluding approver and requester already notified)
    exclude_ids = {approver.id}
    if topic.created_by:
        exclude_ids.add(topic.created_by_id)
    route_users, route_link = get_route(Notification.REVISION_APPROVED)
    route_users = route_users.exclude(id__in=exclude_ids)
    if route_users.exists():
        title, body, link = render_notification(Notification.REVISION_APPROVED, ctx, route_link)
        bulk_notify(
            users=route_users,
            notification_type=Notification.REVISION_APPROVED,
            title=title,
            body=body,
            link=link,
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
        from django.contrib.auth.models import User
        mentioned_ids = set(
            release.release_topic.mentioned_users
            .exclude(id=initiator.id)
            .values_list('id', flat=True)
        )
        _sr_users, _sr_link = get_route(Notification.REVISION_REQUESTED)
        route_ids = set(
            _sr_users
            .exclude(id=initiator.id)
            .values_list('id', flat=True)
        )
        all_ids = mentioned_ids | route_ids
        if all_ids:
            rev = release.revision_code or release.revision_number
            ctx = {
                'actor':         initiator.get_full_name(),
                'job_no':        job_order.job_no,
                'job_title':     job_order.title,
                'revision':      rev,
                'topic_content': reason,
                'topic_id':      release.release_topic.id if release.release_topic else '',
            }
            title, body, link = render_notification(Notification.REVISION_REQUESTED, ctx, _sr_link)
            bulk_notify(
                users=User.objects.filter(id__in=all_ids),
                notification_type=Notification.REVISION_REQUESTED,
                title=title,
                body=body,
                link=link,
                source_type='drawing_release',
                source_id=release.id,
            )

    # Notify all department task assignees (job on hold)
    send_job_on_hold_notifications(job_order, reason, release=release)


def send_job_on_hold_notifications(job_order, reason, release=None):
    """Send notifications to department task assignees + route users when job is on hold."""
    from django.contrib.auth.models import User
    assignee_ids = set(
        job_order.department_tasks
        .filter(assigned_to__isnull=False)
        .values_list('assigned_to_id', flat=True)
    )
    route_users, route_link = get_route(Notification.JOB_ON_HOLD)
    route_ids = set(route_users.values_list('id', flat=True))
    all_ids = assignee_ids | route_ids
    if not all_ids:
        return
    users = User.objects.filter(id__in=all_ids, is_active=True)
    ctx = {
        'job_no': job_order.job_no,
        'reason': reason,
    }
    title, body, link = render_notification(Notification.JOB_ON_HOLD, ctx, route_link)
    bulk_notify(
        users=users,
        notification_type=Notification.JOB_ON_HOLD,
        title=title,
        body=body,
        link=link,
        source_type='job_order',
        source_id=job_order.job_no,
    )


def send_revision_completed_notifications(new_release, new_topic, old_revision_topic, completer):
    """Send notifications when revision is completed and new release is made."""
    job_order = new_release.job_order
    rev = new_release.revision_code or new_release.revision_number

    _rc_users, _rc_link = get_route(Notification.REVISION_COMPLETED)

    ctx = {
        'actor':       completer.get_full_name(),
        'job_no':      job_order.job_no,
        'job_title':   job_order.title,
        'revision':    rev,
        'changelog':   new_release.changelog,
        'folder_path': new_release.folder_path,
        'topic_id':    new_topic.id,
    }
    title, body, link = render_notification(Notification.REVISION_COMPLETED, ctx, _rc_link)

    notified_ids = {completer.id}

    # Notify the original revision requester
    if old_revision_topic and old_revision_topic.created_by and old_revision_topic.created_by != completer:
        notify(
            user=old_revision_topic.created_by,
            notification_type=Notification.REVISION_COMPLETED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=new_release.id,
        )
        notified_ids.add(old_revision_topic.created_by_id)

    # Mentioned users in the new topic + route users, excluding already notified
    from django.contrib.auth.models import User
    mentioned_ids = set(
        new_topic.mentioned_users.exclude(id__in=notified_ids).values_list('id', flat=True)
    )
    route_ids = set(_rc_users.exclude(id__in=notified_ids).values_list('id', flat=True))
    extra_ids = mentioned_ids | route_ids
    if extra_ids:
        bulk_notify(
            users=User.objects.filter(id__in=extra_ids),
            notification_type=Notification.REVISION_COMPLETED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=new_release.id,
        )

    # Notify all department task assignees (job resumed)
    send_job_resumed_notifications(job_order, new_topic, new_release)


def send_job_resumed_notifications(job_order, topic=None, release=None):
    """Send notifications to department task assignees + route users when job is resumed."""
    from django.contrib.auth.models import User
    assignee_ids = set(
        job_order.department_tasks
        .filter(assigned_to__isnull=False)
        .values_list('assigned_to_id', flat=True)
    )
    route_users, route_link = get_route(Notification.JOB_RESUMED)
    route_ids = set(route_users.values_list('id', flat=True))
    all_ids = assignee_ids | route_ids
    if not all_ids:
        return
    users = User.objects.filter(id__in=all_ids, is_active=True)
    rev = (release.revision_code or release.revision_number) if release else None
    ctx = {
        'job_no':   job_order.job_no,
        'revision': f'Yeni Revizyon: {rev}\n\n' if rev else '',
    }
    title, body, link = render_notification(Notification.JOB_RESUMED, ctx, route_link)
    bulk_notify(
        users=users,
        notification_type=Notification.JOB_RESUMED,
        title=title,
        body=body,
        link=link,
        source_type='job_order',
        source_id=job_order.job_no,
    )


def send_revision_rejected_notifications(release, topic, reason, rejecter):
    """Send notification when a revision request is rejected."""
    job_order = release.job_order
    rev = release.revision_code or release.revision_number

    ctx = {
        'actor':       rejecter.get_full_name(),
        'job_no':      job_order.job_no,
        'job_title':   job_order.title,
        'topic_title': topic.title,
        'reason':      reason,
        'topic_id':    topic.id,
    }

    notified_ids = {rejecter.id}

    if topic.created_by and topic.created_by != rejecter:
        title, body, link = render_notification(Notification.REVISION_REJECTED, ctx)
        notify(
            user=topic.created_by,
            notification_type=Notification.REVISION_REJECTED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=release.id,
        )
        notified_ids.add(topic.created_by_id)

    _rr_users, _rr_link = get_route(Notification.REVISION_REJECTED)
    route_users = _rr_users.exclude(id__in=notified_ids)
    if route_users.exists():
        title, body, link = render_notification(Notification.REVISION_REJECTED, ctx, _rr_link)
        bulk_notify(
            users=route_users,
            notification_type=Notification.REVISION_REJECTED,
            title=title,
            body=body,
            link=link,
            source_type='drawing_release',
            source_id=release.id,
        )
