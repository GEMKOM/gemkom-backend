from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import EquipmentItemViewSet, EquipmentCheckoutViewSet

router = DefaultRouter()
router.register(r'items', EquipmentItemViewSet, basename='equipment-item')
router.register(r'checkouts', EquipmentCheckoutViewSet, basename='equipment-checkout')

urlpatterns = [
    path('', include(router.urls)),
]
