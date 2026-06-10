from django.contrib.auth.models import User
from django.test import TestCase

from notifications.models import Notification, NotificationConfig
from notifications.service import get_route
from organization.models import Position, UserGroup


class NotificationRouteUserGroupCompatibilityTests(TestCase):
    def test_get_route_accepts_legacy_user_group_name(self):
        position = Position.objects.create(
            title='Planner',
            level=5,
            department_code='planning',
        )
        user = User.objects.create_user(username='planner')
        user.profile.position = position
        user.profile.save(update_fields=['position'])

        user_group = UserGroup.objects.create(name='Planning', slug='planning')
        user_group.positions.add(position)
        NotificationConfig.objects.create(
            notification_type=Notification.JOB_CANCELLED,
            title_template='Job cancelled',
            body_template='Job cancelled',
            user_groups=['planning'],
            enabled=True,
        )

        users, link = get_route(Notification.JOB_CANCELLED)

        self.assertEqual(link, '')
        self.assertEqual(list(users.order_by('id')), [user])
