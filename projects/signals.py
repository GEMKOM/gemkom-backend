from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import JobOrderDiscussionTopic, JobOrderDiscussionComment, DiscussionNotification
from core.emails import send_plain_email


@receiver(post_save, sender=JobOrderDiscussionTopic)
def handle_topic_created(sender, instance, created, **kwargs):
    """Notify @mentioned users when topic is created."""
    if not created:
        return

    mentioned_users = instance.mentioned_users.exclude(id=instance.created_by_id)

    for user in mentioned_users:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=instance,
            comment=None,
            notification_type='topic_mention',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_topic_mention_email(user, instance)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


@receiver(post_save, sender=JobOrderDiscussionComment)
def handle_comment_created(sender, instance, created, **kwargs):
    """Notify topic owner and @mentioned users when comment is created."""
    if not created:
        return

    topic = instance.topic

    # Notify topic owner
    if topic.created_by and topic.created_by != instance.created_by:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=topic.created_by,
            topic=topic,
            comment=instance,
            notification_type='new_comment',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_new_comment_email(topic.created_by, instance)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify @mentioned users
    mentioned_users = instance.mentioned_users.exclude(id__in=[instance.created_by_id, topic.created_by_id])

    for user in mentioned_users:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            comment=instance,
            notification_type='comment_mention',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_comment_mention_email(user, instance)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_topic_mention_email(user, topic):
    """Send email when user is mentioned in a topic."""
    subject = f"İş Emri Tartışmasında Etiketlendiniz - {topic.job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{topic.created_by.get_full_name()} sizi bir tartışma konusunda etiketledi:

İş Emri: {topic.job_order.job_no} - {topic.job_order.title}
Konu: {topic.title}
Öncelik: {topic.get_priority_display()}

İçerik:
{topic.content}

---
Tartışmayı görüntülemek için sisteme giriş yapınız.

GEMKOM Backend Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for user {user.username}: {e}")


def send_new_comment_email(user, comment):
    """Send email when someone comments on user's topic."""
    topic = comment.topic
    subject = f"Tartışma Konunuza Yeni Yorum - {topic.job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{comment.created_by.get_full_name()} tartışma konunuza yorum yaptı:

İş Emri: {topic.job_order.job_no} - {topic.job_order.title}
Konu: {topic.title}

Yorum:
{comment.content}

---
Tartışmayı görüntülemek için sisteme giriş yapınız.

GEMKOM Backend Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for user {user.username}: {e}")


def send_comment_mention_email(user, comment):
    """Send email when user is mentioned in a comment."""
    topic = comment.topic
    subject = f"Yorumda Etiketlendiniz - {topic.job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{comment.created_by.get_full_name()} sizi bir yorumda etiketledi:

İş Emri: {topic.job_order.job_no} - {topic.job_order.title}
Konu: {topic.title}

Yorum:
{comment.content}

---
Tartışmayı görüntülemek için sisteme giriş yapınız.

GEMKOM Backend Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for user {user.username}: {e}")
