import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from .models import Notification
from .views import SendEmailTaskView


class SendEmailTaskViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='recipient',
            email='recipient@example.com',
        )

    @override_settings(USE_CLOUD_TASKS=False)
    def test_smtp_failure_returns_retryable_status(self):
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.PASSWORD_RESET,
            category=Notification.CATEGORY_GENERAL,
            title='Password reset',
            body='Reset requested',
        )
        request = self.factory.post(
            '/notifications/tasks/send-email/',
            data=json.dumps({
                'to': 'recipient@example.com',
                'subject': 'Password reset',
                'body': 'Reset requested',
                'notification_id': notification.id,
            }),
            content_type='application/json',
        )

        with patch('notifications.views.send_plain_email', side_effect=TimeoutError('smtp timeout')):
            response = SendEmailTaskView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        notification.refresh_from_db()
        self.assertFalse(notification.is_emailed)
        self.assertEqual(notification.email_error, 'smtp timeout')
