"""
Central notification dispatch.

Usage:
    from notifications.service import notify, bulk_notify
    from notifications.models import Notification

    notify(user, Notification.PR_APPROVED, title="...", body="...", link="...")
    bulk_notify(users_qs, Notification.PR_APPROVAL_REQUESTED, title="...", ...)
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings

from .models import Notification, NotificationPreference, NotificationRoute

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default preferences (send_email, send_in_app)
# Rows only exist in NotificationPreference when the user deviates from these.
# ---------------------------------------------------------------------------
NOTIFICATION_DEFAULTS: dict[str, tuple[bool, bool]] = {
    Notification.PR_APPROVAL_REQUESTED:    (True,  True),
    Notification.PR_APPROVED:              (True,  True),
    Notification.PR_REJECTED:              (True,  True),
    Notification.PR_PO_CREATED:            (True,  True),
    Notification.OT_APPROVAL_REQUESTED:    (True,  True),
    Notification.OT_APPROVED:              (True,  True),
    Notification.OT_REJECTED:              (True,  True),
    Notification.QC_REVIEW_SUBMITTED:      (True,  True),
    Notification.QC_REVIEW_APPROVED:       (True,  True),
    Notification.QC_REVIEW_REJECTED:       (True,  True),
    Notification.NCR_CREATED:              (True,  True),
    Notification.NCR_SUBMITTED:            (True,  True),
    Notification.NCR_APPROVED:             (True,  True),
    Notification.NCR_REJECTED:             (True,  True),
    Notification.NCR_ASSIGNED:             (True,  True),
    Notification.SALES_APPROVAL_REQUESTED: (True,  True),
    Notification.SALES_APPROVED:           (True,  True),
    Notification.SALES_REJECTED:           (True,  True),
    Notification.SALES_CONSULTATION:       (True,  True),
    Notification.SALES_CONVERTED:          (True,  True),
    Notification.SUB_APPROVAL_REQUESTED:   (True,  True),
    Notification.SUB_APPROVED:             (True,  True),
    Notification.SUB_REJECTED:             (True,  True),
    Notification.PLAN_APPROVAL_REQUESTED:  (True,  True),
    Notification.PLAN_APPROVED:            (True,  True),
    Notification.PLAN_REJECTED:            (True,  True),
    Notification.PLAN_DR_APPROVED:         (True,  True),
    Notification.DRAWING_RELEASED:         (True,  True),
    Notification.REVISION_REQUESTED:       (True,  True),
    Notification.REVISION_APPROVED:        (True,  True),
    Notification.REVISION_COMPLETED:       (True,  True),
    Notification.REVISION_REJECTED:        (True,  True),
    Notification.JOB_ON_HOLD:              (False, True),   # in-app only — too noisy for email
    Notification.JOB_RESUMED:              (False, True),   # in-app only
    Notification.TOPIC_MENTION:            (True,  True),
    Notification.COMMENT_MENTION:          (True,  True),
    Notification.NEW_COMMENT:              (False, True),   # in-app only
    Notification.PASSWORD_RESET:           (True,  False),  # email only, no in-app needed
}


def get_route_users(notification_type: str):
    """
    Return the configured extra User queryset for a routable notification type.
    Returns an empty queryset if no route exists or the route is disabled.
    """
    from django.contrib.auth.models import User
    try:
        route = NotificationRoute.objects.get(notification_type=notification_type)
        if not route.enabled:
            return User.objects.none()
        return route.users.filter(is_active=True)
    except NotificationRoute.DoesNotExist:
        return User.objects.none()


def _get_user_prefs(user, notification_type: str) -> tuple[bool, bool]:
    """Return (send_email, send_in_app), falling back to NOTIFICATION_DEFAULTS."""
    try:
        pref = NotificationPreference.objects.get(user=user, notification_type=notification_type)
        return pref.send_email, pref.send_in_app
    except NotificationPreference.DoesNotExist:
        return NOTIFICATION_DEFAULTS.get(notification_type, (True, True))


def notify(
    user,
    notification_type: str,
    title: str,
    body: str = '',
    link: str = '',
    source_type: str = '',
    source_id: int | None = None,
    email_subject: str | None = None,
    email_body: str | None = None,
) -> Notification | None:
    """
    Dispatch a single notification to one user.

    Creates an in-app Notification record if the user's preference allows.
    Enqueues a Cloud Tasks email job if the user's preference allows.
    Returns the created Notification (or None if in-app is disabled and no record needed).
    """
    send_email, send_in_app = _get_user_prefs(user, notification_type)

    notification = None
    if send_in_app:
        try:
            notification = Notification.objects.create(
                user=user,
                notification_type=notification_type,
                title=title,
                body=body,
                link=link,
                source_type=source_type,
                source_id=source_id,
            )
        except Exception:
            logger.exception('Failed to create in-app notification for user %s type %s', user, notification_type)

    if send_email and getattr(user, 'email', ''):
        _enqueue_email(
            to=user.email,
            subject=email_subject or title,
            body=email_body or body,
            notification_id=notification.id if notification else None,
        )

    return notification


def bulk_notify(
    users: Iterable,
    notification_type: str,
    title: str,
    body: str = '',
    link: str = '',
    source_type: str = '',
    source_id: int | None = None,
    email_subject: str | None = None,
    email_body: str | None = None,
) -> list[Notification]:
    """
    Dispatch the same notification to multiple users efficiently.
    Uses bulk_create for in-app records (single INSERT), then enqueues
    one email task per eligible recipient.
    """
    users = list(users)
    if not users:
        return []

    # Batch-load existing preference rows for all users at once
    user_ids = [u.id for u in users]
    pref_map: dict[int, tuple[bool, bool]] = {}
    for pref in NotificationPreference.objects.filter(
        user_id__in=user_ids,
        notification_type=notification_type,
    ):
        pref_map[pref.user_id] = (pref.send_email, pref.send_in_app)

    default_email, default_inapp = NOTIFICATION_DEFAULTS.get(notification_type, (True, True))

    to_create = []
    email_recipients: list[tuple[str, int | None]] = []  # (email, placeholder_index)

    for user in users:
        send_email, send_in_app = pref_map.get(user.id, (default_email, default_inapp))
        if send_in_app:
            to_create.append(Notification(
                user=user,
                notification_type=notification_type,
                title=title,
                body=body,
                link=link,
                source_type=source_type,
                source_id=source_id,
            ))
        if send_email and getattr(user, 'email', ''):
            # We'll match the notification id after bulk_create
            email_recipients.append((user.email, len(to_create) - 1 if send_in_app else None))

    created: list[Notification] = []
    if to_create:
        try:
            created = Notification.objects.bulk_create(to_create)
        except Exception:
            logger.exception('bulk_create failed for notification type %s', notification_type)

    # Enqueue emails
    for email, idx in email_recipients:
        notification_id = created[idx].id if (idx is not None and idx < len(created)) else None
        _enqueue_email(
            to=email,
            subject=email_subject or title,
            body=email_body or body,
            notification_id=notification_id,
        )

    return created


def _enqueue_email(to: str, subject: str, body: str, notification_id: int | None = None):
    """
    Enqueue an email via Google Cloud Tasks (HTTP push).
    Falls back to synchronous send when USE_CLOUD_TASKS is False (local dev).
    """
    if not getattr(settings, 'USE_CLOUD_TASKS', True):
        # Synchronous fallback for local development
        from core.emails import send_plain_email
        try:
            send_plain_email(subject=subject, body=body, to=to)
            if notification_id:
                from django.utils import timezone
                Notification.objects.filter(pk=notification_id).update(
                    is_emailed=True,
                    emailed_at=timezone.now(),
                )
        except Exception:
            logger.exception('Synchronous email failed to %s', to)
        return

    try:
        from notifications.tasks import enqueue_send_email
        enqueue_send_email(
            to=to,
            subject=subject,
            body=body,
            notification_id=notification_id,
        )
    except Exception:
        logger.exception('Failed to enqueue email task to %s', to)
