# overtime/urls.py
from rest_framework.routers import DefaultRouter
from .views import OvertimeRequestViewSet

router = DefaultRouter()
router.register(r"requests", OvertimeRequestViewSet, basename="overtime-request")

urlpatterns = router.urls
