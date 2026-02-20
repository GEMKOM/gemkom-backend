from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import QCReviewViewSet, NCRViewSet

router = DefaultRouter()
router.register(r'qc-reviews', QCReviewViewSet)
router.register(r'ncrs', NCRViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
