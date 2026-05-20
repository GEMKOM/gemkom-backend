import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"], USE_CLOUD_TASKS=True, QUEUE_SECRET="")
class SendEmailTaskViewTests(TestCase):
    def test_task_endpoint_fails_closed_without_configured_secret(self):
        payload = {"to": "victim@example.com", "subject": "Hello", "body": "Body"}

        with patch("notifications.views.send_plain_email") as send_plain_email:
            response = Client().post(
                "/notifications/tasks/send-email/",
                data=json.dumps(payload),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        send_plain_email.assert_not_called()
