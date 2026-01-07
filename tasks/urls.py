from rest_framework.routers import DefaultRouter
from .views import PartViewSet, OperationViewSet, ToolViewSet

router = DefaultRouter()
router.register(r'parts', PartViewSet, basename='part')
router.register(r'operations', OperationViewSet, basename='operation')
router.register(r'tools', ToolViewSet, basename='tool')

urlpatterns = router.urls
