from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from finance.views import FinanceReportViewSet, MonthlyExpenseViewSet
from procurement.views import DBSPaymentViewSet, ProcurementReportViewSet, PurchaseOrderViewSet
from sales.views import SalesReportViewSet
from users.permissions import IsFinanceAuthorized


class _FakeUser:
    is_authenticated = True

    def __init__(self, permissions=(), *, is_superuser=False):
        self._permissions = set(permissions)
        self.is_superuser = is_superuser
        self.is_staff = False

    def has_perm(self, permission):
        return permission in self._permissions


class FinanceAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def _response_for(self, view, method, path, user=None, data=None):
        request = getattr(self.factory, method.lower())(path, data=data or {}, format="json")
        force_authenticate(request, user=user or _FakeUser())
        return view(request)

    def test_finance_permission_accepts_existing_finance_codenames(self):
        request = self.factory.get("/finance/reports/inflow-tracker/")
        request.user = _FakeUser({"users.access_finance_reports"})

        self.assertTrue(IsFinanceAuthorized().has_permission(request, view=None))

    def test_finance_permission_rejects_authenticated_non_finance_user(self):
        request = self.factory.get("/finance/reports/inflow-tracker/")
        request.user = _FakeUser({"users.workshop_access"})

        self.assertFalse(IsFinanceAuthorized().has_permission(request, view=None))

    def test_finance_app_routes_reject_non_finance_user_before_queryset(self):
        view = MonthlyExpenseViewSet.as_view({"get": "list"})

        response = self._response_for(view, "get", "/finance/expenses/")

        self.assertEqual(response.status_code, 403)

    def test_finance_reports_reject_non_finance_user_before_report_build(self):
        view = FinanceReportViewSet.as_view({"get": "inflow_tracker"})

        response = self._response_for(view, "get", "/finance/reports/inflow-tracker/")

        self.assertEqual(response.status_code, 403)

    def test_sales_finance_reports_reject_non_finance_user_before_report_build(self):
        view = SalesReportViewSet.as_view({"get": "revenue"})

        response = self._response_for(view, "get", "/sales/reports/revenue/")

        self.assertEqual(response.status_code, 403)

    def test_procurement_finance_reports_reject_non_finance_user_before_report_build(self):
        view = ProcurementReportViewSet.as_view({"get": "payment_forecast"})

        response = self._response_for(view, "get", "/procurement/reports/payment-forecast/")

        self.assertEqual(response.status_code, 403)

    def test_dbs_payment_routes_reject_non_finance_user_before_queryset(self):
        view = DBSPaymentViewSet.as_view({"get": "list"})

        response = self._response_for(view, "get", "/procurement/dbs-payments/")

        self.assertEqual(response.status_code, 403)

    def test_purchase_order_paid_action_rejects_non_finance_user_before_lookup(self):
        view = PurchaseOrderViewSet.as_view({"post": "mark_schedule_paid"})

        response = self._response_for(
            view,
            "post",
            "/procurement/purchase-orders/1/mark_schedule_paid/",
            data={"schedule_id": 1, "paid_with_tax": True},
        )

        self.assertEqual(response.status_code, 403)
