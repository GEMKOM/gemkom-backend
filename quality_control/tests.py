from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


User = get_user_model()


class QualityDocumentPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_unauthenticated_requests_are_rejected(self):
        list_response = self.client.get('/quality-control/documents/')
        delete_response = self.client.delete('/quality-control/documents/999/')

        self.assertIn(list_response.status_code, (401, 403))
        self.assertIn(delete_response.status_code, (401, 403))

    def test_authenticated_user_without_document_permission_is_rejected(self):
        user = User.objects.create_user(username='operator', password='pw')
        self.client.force_authenticate(user=user)

        response = self.client.get('/quality-control/documents/')

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_access_documents(self):
        user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='pw',
        )
        self.client.force_authenticate(user=user)

        response = self.client.get('/quality-control/documents/')

        self.assertEqual(response.status_code, 200)
