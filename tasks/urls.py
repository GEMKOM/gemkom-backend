from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import PartViewSet, OperationViewSet, ToolViewSet, PartStatsView
from .queue_views import DrainCostQueueView

router = DefaultRouter()
router.register(r'parts', PartViewSet, basename='part')
router.register(r'operations', OperationViewSet, basename='operation')
router.register(r'tools', ToolViewSet, basename='tool')

# Stats endpoints (must come BEFORE router.urls to match first)
stats_urlpatterns = [
    path("parts/stats/", PartStatsView.as_view(), name='part-stats'),
]

# Queue endpoints for background processing
queue_urlpatterns = [
    path("internal/drain-part-cost-queue/", DrainCostQueueView.as_view()),
]

# Put specific paths before router URLs to avoid being caught by router patterns
urlpatterns = stats_urlpatterns + queue_urlpatterns + router.urls
