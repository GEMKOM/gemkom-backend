from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import PartViewSet, OperationViewSet, ToolViewSet
from .queue_views import DrainCostQueueView

router = DefaultRouter()
router.register(r'parts', PartViewSet, basename='part')
router.register(r'operations', OperationViewSet, basename='operation')
router.register(r'tools', ToolViewSet, basename='tool')

# Queue endpoints for background processing
queue_urlpatterns = [
    path("internal/drain-part-cost-queue/", DrainCostQueueView.as_view()),
]

urlpatterns = router.urls + queue_urlpatterns
