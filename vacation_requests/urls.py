from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CreditAnnualLeaveView, LeaveBalanceLedgerView, MyLeaveSummaryView, UpcomingLeavesView, UserLeaveBalanceViewSet, UserLeaveSetupView, VacationPreviewView, VacationRequestViewSet

router = DefaultRouter()
router.register(r"requests", VacationRequestViewSet, basename="vacation-request")
router.register(r"balances", UserLeaveBalanceViewSet, basename="leave-balance")

urlpatterns = [
    path("", include(router.urls)),
    path("preview/", VacationPreviewView.as_view(), name="vacation-preview"),
    path("internal/credit-annual-leave/", CreditAnnualLeaveView.as_view(), name="credit-annual-leave"),
    path("users/<int:user_id>/leave-setup/", UserLeaveSetupView.as_view(), name="user-leave-setup"),
    path("upcoming-leaves/", UpcomingLeavesView.as_view(), name="upcoming-leaves"),
    path("my-summary/", MyLeaveSummaryView.as_view(), name="my-leave-summary"),
    path("users/<int:user_id>/leave-ledger/", LeaveBalanceLedgerView.as_view(), name="leave-balance-ledger"),
]
