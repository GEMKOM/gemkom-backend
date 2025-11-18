from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DepartmentRequestViewSet,
    PlanningRequestViewSet,
    PlanningRequestItemViewSet,
    ItemSuggestionView,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'department-requests', DepartmentRequestViewSet, basename='department-requests')
router.register(r'requests', PlanningRequestViewSet, basename='planning-requests')
router.register(r'items', PlanningRequestItemViewSet, basename='planning-request-items')

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
    path('item-suggestions/', ItemSuggestionView.as_view(), name='item-suggestions'),
]
