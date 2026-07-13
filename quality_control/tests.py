from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import UserPermissionOverride


class QualityDocumentPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='quality-user')

    def test_documents_endpoint_rejects_anonymous_requests(self):
        response = self.client.get('/quality-control/documents/')

        self.assertIn(response.status_code, (401, 403))

    def test_documents_endpoint_requires_quality_document_permission(self):
        self.client.force_authenticate(self.user)

        forbidden_response = self.client.get('/quality-control/documents/')
        self.assertEqual(forbidden_response.status_code, 403)

        UserPermissionOverride.objects.create(
            user=self.user,
            codename='access_quality_control_documents',
            granted=True,
        )
        allowed_response = self.client.get('/quality-control/documents/')

        self.assertEqual(allowed_response.status_code, 200)
