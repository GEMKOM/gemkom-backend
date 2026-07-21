from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import CraneRateViewSet, CraneRequestViewSet, CraneTypeViewSet

router = DefaultRouter()
router.register(r'crane-types', CraneTypeViewSet, basename='crane-type')
router.register(r'rates', CraneRateViewSet, basename='crane-rate')
router.register(r'requests', CraneRequestViewSet, basename='crane-request')

urlpatterns = [
    path('', include(router.urls)),
]
