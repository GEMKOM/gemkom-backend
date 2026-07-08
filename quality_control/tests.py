from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from rest_framework.permissions import IsAuthenticated
from rest_framework.test import APIRequestFactory

from .views import (
    CanAccessQualityDocuments,
    NCRViewSet,
    QCReviewViewSet,
    QualityDocumentViewSet,
)


class QualityControlPermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def assert_anonymous_list_denied(self, viewset, path):
        request = self.factory.get(path)
        response = viewset.as_view({'get': 'list'})(request)
        self.assertIn(response.status_code, (401, 403))

    def test_quality_documents_require_auth_and_page_permission(self):
        self.assertIn(IsAuthenticated, QualityDocumentViewSet.permission_classes)
        self.assertIn(CanAccessQualityDocuments, QualityDocumentViewSet.permission_classes)

    def test_quality_document_permission_rejects_anonymous_users(self):
        request = self.factory.get('/quality-control/documents/')
        request.user = AnonymousUser()

        self.assertFalse(CanAccessQualityDocuments().has_permission(request, None))

    def test_quality_document_permission_allows_superusers(self):
        request = self.factory.get('/quality-control/documents/')
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        self.assertTrue(CanAccessQualityDocuments().has_permission(request, None))

    def test_quality_control_viewsets_reject_anonymous_list_requests(self):
        self.assert_anonymous_list_denied(QCReviewViewSet, '/quality-control/qc-reviews/')
        self.assert_anonymous_list_denied(NCRViewSet, '/quality-control/ncrs/')
        self.assert_anonymous_list_denied(QualityDocumentViewSet, '/quality-control/documents/')
