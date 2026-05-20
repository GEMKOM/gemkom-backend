from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework.test import APITestCase

from procurement.models import DBSPayment, Supplier
from users.models import UserProfile


def grant_user_permission(user, codename):
    content_type = ContentType.objects.get_for_model(UserProfile)
    permission, _ = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={"name": codename},
    )
    user.user_permissions.add(permission)


@override_settings(ALLOWED_HOSTS=["testserver"])
class FinancePermissionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="plain", password="pw")
        self.finance_user = User.objects.create_user(username="finance", password="pw")
        grant_user_permission(self.finance_user, "access_finance")

    def test_finance_endpoints_require_access_finance(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/finance/expenses/")
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(self.finance_user)
        response = self.client.get("/finance/expenses/")
        self.assertEqual(response.status_code, 200)

    def test_dbs_payments_require_access_finance(self):
        supplier = Supplier.objects.create(
            name="DBS Supplier",
            has_dbs=True,
            dbs_used=Decimal("100.00"),
            dbs_currency="EUR",
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": supplier.id, "amount": "10.00", "note": "repayment"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(DBSPayment.objects.exists())

    def test_dbs_payment_cannot_exceed_used_balance(self):
        supplier = Supplier.objects.create(
            name="DBS Supplier",
            has_dbs=True,
            dbs_used=Decimal("100.00"),
            dbs_currency="EUR",
        )
        self.client.force_authenticate(self.finance_user)
        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": supplier.id, "amount": "150.00", "note": "overpayment"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DBSPayment.objects.exists())
        supplier.refresh_from_db()
        self.assertEqual(supplier.dbs_used, Decimal("100.00"))

    def test_dbs_payment_records_and_decrements_balance_atomically(self):
        supplier = Supplier.objects.create(
            name="DBS Supplier",
            has_dbs=True,
            dbs_used=Decimal("100.00"),
            dbs_currency="EUR",
        )
        self.client.force_authenticate(self.finance_user)
        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": supplier.id, "amount": "40.00", "note": "repayment"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(DBSPayment.objects.count(), 1)
        supplier.refresh_from_db()
        self.assertEqual(supplier.dbs_used, Decimal("60.00"))
