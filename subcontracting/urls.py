from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .queue_views import DrainSubcontractorCostQueueView
from .views import (
    SubcontractingAssignmentViewSet,
    SubcontractingPriceTierViewSet,
    SubcontractorStatementAdjustmentViewSet,
    SubcontractorStatementViewSet,
    SubcontractorViewSet,
)

router = DefaultRouter()
router.register(r'subcontractors', SubcontractorViewSet, basename='subcontractor')
router.register(r'price-tiers', SubcontractingPriceTierViewSet, basename='price-tier')
router.register(r'assignments', SubcontractingAssignmentViewSet, basename='assignment')
router.register(r'statements', SubcontractorStatementViewSet, basename='statement')

urlpatterns = [
    path('', include(router.urls)),

    # Nested adjustments: /subcontracting/statements/{statement_pk}/adjustments/
    path(
        'statements/<int:statement_pk>/adjustments/',
        SubcontractorStatementAdjustmentViewSet.as_view({'get': 'list', 'post': 'create'}),
        name='statement-adjustment-list',
    ),
    path(
        'statements/<int:statement_pk>/adjustments/<int:pk>/',
        SubcontractorStatementAdjustmentViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'}),
        name='statement-adjustment-detail',
    ),

    # Internal background queue drain
    path(
        'internal/drain-cost-queue/',
        DrainSubcontractorCostQueueView.as_view(),
        name='drain-subcontractor-cost-queue',
    ),
]
