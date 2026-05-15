from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AdHocJobCostViewSet,
    ExpectedReceiptViewSet,
    FinanceReportViewSet,
    LoanViewSet,
    MonthlyExpenseViewSet,
    TaxEntryViewSet,
)

router = DefaultRouter()
router.register(r"expenses", MonthlyExpenseViewSet, basename="finance-expense")
router.register(r"loans", LoanViewSet, basename="finance-loan")
router.register(r"taxes", TaxEntryViewSet, basename="finance-tax")
router.register(r"expected-receipts", ExpectedReceiptViewSet, basename="finance-receipt")
router.register(r"adhoc-costs", AdHocJobCostViewSet, basename="finance-adhoc")
router.register(r"reports", FinanceReportViewSet, basename="finance-report")

urlpatterns = [
    path("", include(router.urls)),
]
