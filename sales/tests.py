from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from notifications.models import Notification, NotificationConfig
from notifications.service import invalidate_config_cache
from projects.models import Customer, JobOrder

from .models import SalesOffer
from .services import _send_order_confirmed_notification


class OrderConfirmedNotificationTests(TestCase):
    def setUp(self):
        self.route_user = User.objects.create_user(
            username='route-user',
            email='route@example.com',
        )
        self.creator = User.objects.create_user(
            username='creator',
            email='creator@example.com',
        )

        config, _ = NotificationConfig.objects.update_or_create(
            notification_type=Notification.SALES_ORDER_CONFIRMED,
            defaults={
                'title_template': 'Order confirmed {job_no}',
                'body_template': 'Offer {offer_no} confirmed for {customer}. {link}',
                'link_template': 'https://example.test/jobs/{job_no}',
                'available_vars': ['offer_no', 'customer', 'job_no', 'link'],
                'default_send_email': True,
                'default_send_in_app': False,
                'teams': [],
                'groups': [],
                'user_groups': [],
                'enabled': True,
            },
        )
        config.users.set([self.route_user])
        invalidate_config_cache()

        self.customer = Customer.objects.create(
            code='C001',
            name='Acme Steel',
        )
        self.job_order = JobOrder.objects.create(
            job_no='C001-01',
            title='Confirmed job',
            customer=self.customer,
        )
        self.offer = SalesOffer.objects.create(
            offer_no='OF-2026-0001',
            customer=self.customer,
            title='Confirmed offer',
            status='won',
            created_by=self.creator,
        )

    def tearDown(self):
        invalidate_config_cache()

    def test_order_confirmed_email_is_queued_when_no_receipt_attachment_exists(self):
        with (
            patch('notifications.service._enqueue_email') as enqueue_email,
            patch('core.emails.send_email_with_attachments') as send_with_attachments,
        ):
            _send_order_confirmed_notification(self.offer, self.job_order)

        send_with_attachments.assert_not_called()
        self.assertCountEqual(
            [call.kwargs['to'] for call in enqueue_email.call_args_list],
            ['route@example.com', 'creator@example.com'],
        )
        for call in enqueue_email.call_args_list:
            self.assertIn('Order confirmed C001-01', call.kwargs['subject'])
            self.assertIn('OF-2026-0001', call.kwargs['body'])
