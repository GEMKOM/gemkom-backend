from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory

from .views import HasQualityDocumentAccess, NCRViewSet, QCReviewViewSet, QualityDocumentViewSet


class QualityControlPermissionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.regular_user = User.objects.create_user(username="regular")
        self.superuser = User.objects.create_superuser(username="superuser")

    def _has_permission(self, permission_class, user):
        request = self.factory.get("/quality-control/documents/")
        request.user = user
        return permission_class().has_permission(request, QualityDocumentViewSet())

    def test_quality_document_access_requires_role_permission(self):
        self.assertFalse(self._has_permission(HasQualityDocumentAccess, AnonymousUser()))
        self.assertFalse(self._has_permission(HasQualityDocumentAccess, self.regular_user))
        self.assertTrue(self._has_permission(HasQualityDocumentAccess, self.superuser))

    def test_quality_control_viewsets_require_authentication(self):
        self.assertEqual(QCReviewViewSet.permission_classes, [IsAuthenticated])
        self.assertEqual(NCRViewSet.permission_classes, [IsAuthenticated])
