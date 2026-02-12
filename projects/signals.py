import threading
from django.utils import timezone
from .models import DiscussionNotification
from core.emails import send_plain_email


def send_topic_notifications(topic):
    """Send notifications to @mentioned users in a topic."""
    mentioned_users = topic.mentioned_users.exclude(id=topic.created_by_id)

    for user in mentioned_users:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            comment=None,
            notification_type='topic_mention',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_topic_mention_email(user, topic)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_comment_notifications(comment):
    """Send notifications to topic owner and @mentioned users."""
    topic = comment.topic

    # Notify topic owner (if someone else commented)
    if topic.created_by and topic.created_by != comment.created_by:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=topic.created_by,
            topic=topic,
            comment=comment,
            notification_type='new_comment',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_new_comment_email(topic.created_by, comment)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify @mentioned users (excluding comment author and topic owner)
    exclude_ids = [comment.created_by_id]
    if topic.created_by_id:
        exclude_ids.append(topic.created_by_id)

    mentioned_users = comment.mentioned_users.exclude(id__in=exclude_ids)

    for user in mentioned_users:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            comment=comment,
            notification_type='comment_mention',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_comment_mention_email(user, comment)
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
Tartışmayı görüntülemek için aşağıdaki linke tıklayınız.
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={topic.job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
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
Tartışmayı görüntülemek için aşağıdaki linke tıklayınız.
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={topic.job_order.job_no}&topic_id={topic.id}

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
Tartışmayı görüntülemek için aşağıdaki linke tıklayınız.
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={topic.job_order.job_no}&topic_id={topic.id}

GEMKOM Backend Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for user {user.username}: {e}")


# ============================================================================
# Technical Drawing Release Notification Functions
# ============================================================================

def send_drawing_released_notifications(release, topic):
    """Send notifications when technical drawings are released."""
    job_order = release.job_order

    # Collect users to notify and create DB notifications
    users_to_email = []
    for user in topic.mentioned_users.exclude(id=release.released_by_id):
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            notification_type='drawing_released',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            users_to_email.append(user)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Send emails in background thread
    if users_to_email:
        def _send_emails():
            pass
            # for user in users_to_email:
            #     send_drawing_released_email(user, release, topic)

        threading.Thread(target=_send_emails, daemon=True).start()


def send_drawing_released_email(user, release, topic):
    """Send email when technical drawings are released."""
    job_order = release.job_order
    subject = f"Teknik Çizim Yayınlandı - {job_order.job_no} Rev.{release.revision_code or release.revision_number}"
    body = f"""Merhaba {user.get_full_name()},

{release.released_by.get_full_name()} yeni teknik çizim yayınladı:

İş Emri: {job_order.job_no} - {job_order.title}
Revizyon: {release.revision_code or release.revision_number}
Hardcopy: {release.hardcopy_count} set planlama birimine bırakılacaktır.

Klasör Yolu:
{release.folder_path}

Değişiklikler:
{release.changelog}

---
Tartışmayı görüntülemek için aşağıdaki linke tıklayınız.
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for drawing release to {user.username}: {e}")


def send_revision_requested_notifications(release, topic, requester):
    """Send notifications when a revision is requested (pending approval)."""
    job_order = release.job_order

    # Notify design task assignee
    design_task = job_order.department_tasks.filter(
        department='design',
        parent__isnull=True
    ).first()

    if design_task and design_task.assigned_to and design_task.assigned_to != requester:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=design_task.assigned_to,
            topic=topic,
            notification_type='revision_requested',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_revision_requested_email(design_task.assigned_to, release, topic, requester)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Also notify the original releaser if different from design task assignee
    if release.released_by and release.released_by != requester:
        if not design_task or release.released_by != design_task.assigned_to:
            notification, created = DiscussionNotification.objects.get_or_create(
                user=release.released_by,
                topic=topic,
                notification_type='revision_requested',
                defaults={'is_read': False, 'is_emailed': False}
            )

            if created:
                send_revision_requested_email(release.released_by, release, topic, requester)
                notification.is_emailed = True
                notification.emailed_at = timezone.now()
                notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_revision_requested_email(user, release, topic, requester):
    """Send email when a revision is requested."""
    job_order = release.job_order
    subject = f"Revizyon Talebi - {job_order.job_no} Rev.{release.revision_code or release.revision_number}"
    body = f"""Merhaba {user.get_full_name()},

{requester.get_full_name()} teknik çizimler için revizyon talep etti:

İş Emri: {job_order.job_no} - {job_order.title}
Mevcut Revizyon: {release.revision_code or release.revision_number}

Talep Nedeni:
{topic.content}

Bu talep onay beklemektedir. Onayladığınızda iş emri beklemeye alınacaktır.

---
Talebi incelemek için aşağıdaki linke tıklayınız.
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for revision request to {user.username}: {e}")


def send_revision_approved_notifications(release, topic, approver):
    """Send notifications when a revision is approved (job on hold)."""
    job_order = release.job_order

    # Notify the original requester
    if topic.created_by and topic.created_by != approver:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=topic.created_by,
            topic=topic,
            notification_type='revision_approved',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_revision_approved_email(topic.created_by, release, topic, approver)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify all department task assignees (job on hold)
    send_job_on_hold_notifications(job_order, topic, f"Revizyon onaylandı: {topic.title}")


def send_revision_approved_email(user, release, topic, approver):
    """Send email when revision is approved."""
    job_order = release.job_order
    subject = f"Revizyon Onaylandı - {job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{approver.get_full_name()} revizyon talebinizi onayladı:

İş Emri: {job_order.job_no} - {job_order.title}
Konu: {topic.title}

İş emri revizyon süresince beklemeye alınmıştır.

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for revision approved to {user.username}: {e}")


def send_self_revision_notifications(release, topic, initiator):
    """Send notifications when designer self-initiates a revision."""
    job_order = release.job_order

    # Get stakeholders from the original release topic
    if release.release_topic:
        for user in release.release_topic.mentioned_users.exclude(id=initiator.id):
            notification, created = DiscussionNotification.objects.get_or_create(
                user=user,
                topic=topic,
                notification_type='revision_requested',
                defaults={'is_read': False, 'is_emailed': False}
            )

            if created:
                send_self_revision_email(user, release, topic, initiator)
                notification.is_emailed = True
                notification.emailed_at = timezone.now()
                notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify all department task assignees (job on hold)
    send_job_on_hold_notifications(job_order, topic, f"Tasarımcı revizyon başlattı: {topic.title}")


def send_self_revision_email(user, release, topic, initiator):
    """Send email when designer self-initiates revision."""
    job_order = release.job_order
    subject = f"⚠️ Revizyon Başlatıldı - {job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{initiator.get_full_name()} teknik çizimlerde revizyon başlattı:

İş Emri: {job_order.job_no} - {job_order.title}
Mevcut Revizyon: {release.revision_code or release.revision_number}

Neden:
{topic.content}

⚠️ İŞ EMRİ BEKLETİLDİ - Revizyon tamamlanana kadar çalışmalar durdurulmuştur.

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for self revision to {user.username}: {e}")


def send_job_on_hold_notifications(job_order, topic, reason):
    """Send notifications to all department task assignees when job is on hold."""
    # Get unique assignees from all department tasks
    assignees = set()
    for task in job_order.department_tasks.filter(assigned_to__isnull=False):
        if task.assigned_to:
            assignees.add(task.assigned_to)

    for user in assignees:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            notification_type='job_on_hold',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_job_on_hold_email(user, job_order, topic, reason)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_job_on_hold_email(user, job_order, topic, reason):
    """Send email when job order is put on hold."""
    subject = f"⏸️ İş Emri Beklemede - {job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{job_order.job_no} numaralı iş emri revizyon nedeniyle bekletilmiştir.

Revizyon tamamlanana kadar bu iş emri üzerindeki çalışmalara devam etmeyiniz.

Neden: {reason}

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for job on hold to {user.username}: {e}")


def send_revision_completed_notifications(new_release, new_topic, old_revision_topic, completer):
    """Send notifications when revision is completed and new release is made."""
    job_order = new_release.job_order

    # Notify the original revision requester
    if old_revision_topic and old_revision_topic.created_by and old_revision_topic.created_by != completer:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=old_revision_topic.created_by,
            topic=new_topic,
            notification_type='revision_completed',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_revision_completed_email(old_revision_topic.created_by, new_release, new_topic, completer)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify mentioned users in the new topic
    for user in new_topic.mentioned_users.exclude(id=completer.id):
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=new_topic,
            notification_type='drawing_released',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_drawing_released_email(user, new_release, new_topic)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])

    # Notify all department task assignees (job resumed)
    send_job_resumed_notifications(job_order, new_topic, new_release)


def send_revision_completed_email(user, release, topic, completer):
    """Send email when revision is completed."""
    job_order = release.job_order
    subject = f"✅ Revizyon Tamamlandı - {job_order.job_no} Rev.{release.revision_code or release.revision_number}"
    body = f"""Merhaba {user.get_full_name()},

{completer.get_full_name()} revizyonu tamamladı ve yeni çizim yayınladı:

İş Emri: {job_order.job_no} - {job_order.title}
Yeni Revizyon: {release.revision_code or release.revision_number}

Değişiklikler:
{release.changelog}

Klasör Yolu:
{release.folder_path}

İş emri devam etmektedir.

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for revision completed to {user.username}: {e}")


def send_job_resumed_notifications(job_order, topic, release):
    """Send notifications to all department task assignees when job is resumed."""
    # Get unique assignees from all department tasks
    assignees = set()
    for task in job_order.department_tasks.filter(assigned_to__isnull=False):
        if task.assigned_to:
            assignees.add(task.assigned_to)

    for user in assignees:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=user,
            topic=topic,
            notification_type='job_resumed',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_job_resumed_email(user, job_order, release)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_job_resumed_email(user, job_order, release):
    """Send email when job order is resumed."""
    subject = f"▶️ İş Emri Devam Ediyor - {job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{job_order.job_no} numaralı iş emri üzerindeki revizyon tamamlanmıştır.

Çalışmalara devam edebilirsiniz.

Yeni Revizyon: {release.revision_code or release.revision_number}

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for job resumed to {user.username}: {e}")


def send_revision_rejected_notifications(release, topic, reason, rejecter):
    """Send notification when a revision request is rejected."""
    job_order = release.job_order

    # Notify the original requester
    if topic.created_by and topic.created_by != rejecter:
        notification, created = DiscussionNotification.objects.get_or_create(
            user=topic.created_by,
            topic=topic,
            notification_type='revision_rejected',
            defaults={'is_read': False, 'is_emailed': False}
        )

        if created:
            send_revision_rejected_email(topic.created_by, release, topic, reason, rejecter)
            notification.is_emailed = True
            notification.emailed_at = timezone.now()
            notification.save(update_fields=['is_emailed', 'emailed_at'])


def send_revision_rejected_email(user, release, topic, reason, rejecter):
    """Send email when revision request is rejected."""
    job_order = release.job_order
    subject = f"Revizyon Talebi Reddedildi - {job_order.job_no}"
    body = f"""Merhaba {user.get_full_name()},

{rejecter.get_full_name()} revizyon talebinizi reddetti:

İş Emri: {job_order.job_no} - {job_order.title}
Konu: {topic.title}

Red Nedeni:
{reason}

---
https://ofis.gemcore.com.tr/projects/project-tracking/?job_no={job_order.job_no}&topic_id={topic.id}

GEMKOM Sistemi
"""

    try:
        send_plain_email(subject=subject, body=body, to=user.email)
    except Exception as e:
        print(f"Email error for revision rejected to {user.username}: {e}")
