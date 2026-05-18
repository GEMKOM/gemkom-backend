from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AdHocJobCostViewSet,
    ExpectedReceiptViewSet,
    FinanceReportViewSet,
    LoanViewSet,
    MonthlyExpenseViewSet,
    SalesOfferInstallmentReceiptViewSet,
    TaxEntryViewSet,
)

router = DefaultRouter()
router.register(r"expenses", MonthlyExpenseViewSet, basename="finance-expense")
router.register(r"loans", LoanViewSet, basename="finance-loan")
router.register(r"taxes", TaxEntryViewSet, basename="finance-tax")
router.register(r"expected-receipts", ExpectedReceiptViewSet, basename="finance-receipt")
router.register(r"adhoc-costs", AdHocJobCostViewSet, basename="finance-adhoc")
router.register(r"reports", FinanceReportViewSet, basename="finance-report")

offer_installment_list = SalesOfferInstallmentReceiptViewSet.as_view({"get": "list"})
offer_installment_mark = SalesOfferInstallmentReceiptViewSet.as_view({"post": "mark_received"})
offer_installment_unmark = SalesOfferInstallmentReceiptViewSet.as_view({"post": "unmark_received"})

urlpatterns = [
    path("", include(router.urls)),
    path("offer-installments/<int:offer_pk>/", offer_installment_list, name="finance-offer-installments-list"),
    path("offer-installments/<int:offer_pk>/<int:sequence>/mark-received/", offer_installment_mark, name="finance-offer-installment-mark-received"),
    path("offer-installments/<int:offer_pk>/<int:sequence>/unmark-received/", offer_installment_unmark, name="finance-offer-installment-unmark-received"),
]
