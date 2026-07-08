from django.test import SimpleTestCase
from rest_framework import permissions

from .views import JobOrderViewSet


class JobOrderPermissionTests(SimpleTestCase):
    def test_job_orders_require_authentication(self):
        self.assertIn(permissions.IsAuthenticated, JobOrderViewSet.permission_classes)
