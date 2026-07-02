from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import QCReviewViewSet, NCRViewSet, QualityDocumentViewSet

router = DefaultRouter()
router.register(r'qc-reviews', QCReviewViewSet)
router.register(r'ncrs', NCRViewSet)
router.register(r'documents', QualityDocumentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
