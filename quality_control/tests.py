from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from users.models import UserProfile


class QualityDocumentPermissionTests(APITestCase):
    def setUp(self):
        self.url = "/quality-control/documents/"
        self.user = User.objects.create_user(username="regular", password="pw")
        self.allowed_user = User.objects.create_user(username="quality-docs", password="pw")

        content_type = ContentType.objects.get_for_model(UserProfile)
        permission, _ = Permission.objects.get_or_create(
            content_type=content_type,
            codename="access_quality_control_documents",
            defaults={"name": "Page: /quality-control/documents/"},
        )
        self.allowed_user.user_permissions.add(permission)

    def test_quality_documents_reject_anonymous_users(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 401)

    def test_quality_documents_require_page_permission(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_quality_documents_allow_users_with_page_permission(self):
        self.client.force_authenticate(self.allowed_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
