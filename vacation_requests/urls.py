from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VacationRequestViewSet, UserLeaveBalanceViewSet, VacationPreviewView

router = DefaultRouter()
router.register(r"requests", VacationRequestViewSet, basename="vacation-request")
router.register(r"balances", UserLeaveBalanceViewSet, basename="leave-balance")

urlpatterns = [
    path("", include(router.urls)),
    path("preview/", VacationPreviewView.as_view(), name="vacation-preview"),
]
