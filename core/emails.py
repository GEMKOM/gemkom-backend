import logging

from django.core.mail import send_mail, EmailMessage
from django.conf import settings

logger = logging.getLogger(__name__)

def send_plain_email(subject: str, body: str, to: list[str] | tuple[str, ...] | str):
    if isinstance(to, str):
        to = [to]
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=to,
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send email to %s: %s", to, subject)


def send_email_with_attachments(
    subject: str,
    body: str,
    to: list[str] | tuple[str, ...] | str,
    attachments: list[tuple[str, bytes, str]] | None = None,
):
    """
    Send an email with optional file attachments.
    attachments: list of (filename, content_bytes, mimetype) tuples.
    """
    if isinstance(to, str):
        to = [to]
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
        )
        for filename, content, mimetype in (attachments or []):
            msg.attach(filename, content, mimetype)
        msg.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send email with attachments to %s: %s", to, subject)