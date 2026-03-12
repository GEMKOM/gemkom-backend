"""
Cloud Tasks integration for async email delivery.

enqueue_send_email() creates an HTTP push task that calls:
    POST /notifications/tasks/send-email/

Cloud Tasks retries on failure (configurable on the queue).
The callback view (SendEmailTaskView) handles the actual SMTP send.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def enqueue_send_email(
    to: str,
    subject: str,
    body: str,
    notification_id: int | None = None,
) -> None:
    """
    Enqueue an HTTP push task to the Cloud Tasks queue.
    The task will POST to /notifications/tasks/send-email/ with an OIDC token.
    """
    from google.cloud import tasks_v2

    project_id  = settings.GCP_PROJECT_ID
    location    = settings.GCP_LOCATION
    queue_name  = settings.CLOUD_TASKS_QUEUE
    service_url = settings.CLOUD_RUN_SERVICE_URL
    sa_email    = settings.CLOUD_TASKS_SERVICE_ACCOUNT

    payload = json.dumps({
        'notification_id': notification_id,
        'to': to,
        'subject': subject,
        'body': body,
    }).encode('utf-8')

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': f'{service_url}/notifications/tasks/send-email/',
            'headers': {
                'Content-Type': 'application/json',
                'X-Task-Secret': settings.QUEUE_SECRET,
            },
            'body': payload,
            'oidc_token': {
                'service_account_email': sa_email,
                'audience': service_url,
            },
        }
    }

    client = tasks_v2.CloudTasksClient()
    parent = f'projects/{project_id}/locations/{location}/queues/{queue_name}'
    client.create_task(parent=parent, task=task)
