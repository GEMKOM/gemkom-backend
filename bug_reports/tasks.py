"""
Cloud Tasks integration for async bug report agent processing.

enqueue_agent_process() creates an HTTP push task that calls:
    POST /bug-reports/tasks/process/{bug_report_id}/

In development (USE_CLOUD_TASKS=false), runs the agent synchronously in a thread.
"""
from __future__ import annotations

import json
import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


def enqueue_agent_process(bug_report_id: int) -> None:
    if not settings.USE_CLOUD_TASKS:
        # Run synchronously in background thread to avoid blocking the request
        thread = threading.Thread(target=_run_agent_sync, args=(bug_report_id,), daemon=True)
        thread.start()
        return

    from google.cloud import tasks_v2

    project_id  = settings.GCP_PROJECT_ID
    location    = settings.GCP_LOCATION
    queue_name  = settings.CLOUD_TASKS_QUEUE
    service_url = settings.CLOUD_RUN_SERVICE_URL
    sa_email    = settings.CLOUD_TASKS_SERVICE_ACCOUNT

    payload = json.dumps({'bug_report_id': bug_report_id}).encode('utf-8')

    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': f'{service_url}/bug-reports/tasks/process/{bug_report_id}/',
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
    logger.info('Enqueued agent task for bug report %s', bug_report_id)


def _run_agent_sync(bug_report_id: int) -> None:
    try:
        import django
        import os
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        if not django.apps.apps.ready:
            django.setup()
        from .agent import process_bug_report
        process_bug_report(bug_report_id)
    except Exception:
        logger.exception('Sync agent run failed for bug report %s', bug_report_id)
