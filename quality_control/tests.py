from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import UserPermissionOverride


class QualityDocumentPermissionTests(APITestCase):
    def setUp(self):
        self.url = reverse('qualitydocument-list')
        User = get_user_model()
        self.user = User.objects.create_user(username='regular', password='testpass')
        self.allowed_user = User.objects.create_user(username='quality', password='testpass')
        UserPermissionOverride.objects.create(
            user=self.allowed_user,
            codename='access_quality_control_documents',
            granted=True,
        )

    def test_documents_require_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_documents_require_quality_document_permission(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_with_quality_document_permission_can_list(self):
        self.client.force_authenticate(self.allowed_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
