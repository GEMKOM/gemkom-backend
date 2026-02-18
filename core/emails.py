import logging

from django.core.mail import send_mail
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