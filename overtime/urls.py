# overtime/urls.py
from rest_framework.routers import DefaultRouter
from .views import OvertimeRequestViewSet, OvertimeUsersForDateView
from django.urls import path, include

router = DefaultRouter()
router.register(r"requests", OvertimeRequestViewSet, basename="overtime-request")

urlpatterns = [
    path('', include(router.urls)),
    path(
        "overtime/users-for-date/<str:date_str>/",
        OvertimeUsersForDateView.as_view(),
        name="overtime-users-for-date"
    ),
]

urlpatterns = router.urls
