from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from procurement.models import DBSPayment, Supplier
from users.models import UserProfile


class DBSPaymentTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="plain", password="pw")
        self.finance_user = User.objects.create_user(username="finance", password="pw")
        self.finance_user.user_permissions.add(self._finance_permission())
        self.supplier = Supplier.objects.create(
            name="DBS Supplier",
            has_dbs=True,
            dbs_used=Decimal("50000.00"),
            dbs_currency="EUR",
        )

    @staticmethod
    def _finance_permission():
        content_type = ContentType.objects.get_for_model(UserProfile)
        permission, _ = Permission.objects.get_or_create(
            codename="access_finance",
            content_type=content_type,
            defaults={"name": "Can access finance"},
        )
        return permission

    def test_authenticated_user_without_finance_permission_cannot_create_dbs_payment(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": self.supplier.id, "amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(DBSPayment.objects.count(), 0)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.dbs_used, Decimal("50000.00"))

    def test_rejects_dbs_payment_greater_than_current_used_balance(self):
        self.client.force_authenticate(self.finance_user)

        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": self.supplier.id, "amount": "80000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(DBSPayment.objects.count(), 0)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.dbs_used, Decimal("50000.00"))

    def test_valid_dbs_payment_records_payment_and_decrements_used_balance(self):
        self.client.force_authenticate(self.finance_user)

        response = self.client.post(
            "/procurement/dbs-payments/",
            {"supplier": self.supplier.id, "amount": "12500.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        payment = DBSPayment.objects.get()
        self.assertEqual(payment.amount, Decimal("12500.00"))
        self.assertEqual(payment.currency, "EUR")
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.dbs_used, Decimal("37500.00"))
