from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from finance.models import Loan, SalesOfferInstallmentReceipt
from finance.serializers import LoanSerializer
from procurement.models import PaymentTerms
from projects.models import Customer
from sales.models import SalesOffer
from users.models import UserProfile


class FinanceAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="plain", password="pw")
        self.finance_user = User.objects.create_user(username="finance", password="pw")
        self.finance_user.user_permissions.add(self._finance_permission())

    @staticmethod
    def _finance_permission():
        content_type = ContentType.objects.get_for_model(UserProfile)
        permission, _ = Permission.objects.get_or_create(
            codename="access_finance",
            content_type=content_type,
            defaults={"name": "Can access finance"},
        )
        return permission

    def test_authenticated_user_without_finance_permission_cannot_create_loan(self):
        self.client.force_authenticate(self.user)

        response = self.client.post("/finance/loans/", self._loan_payload(), format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Loan.objects.count(), 0)

    def test_finance_user_can_create_loan_with_installments(self):
        self.client.force_authenticate(self.finance_user)

        response = self.client.post("/finance/loans/", self._loan_payload(), format="json")

        self.assertEqual(response.status_code, 201)
        loan = Loan.objects.get()
        self.assertEqual(loan.installments.count(), 2)

    def test_loan_create_rolls_back_if_installment_generation_fails(self):
        serializer = LoanSerializer(
            data=self._loan_payload(name="Broken loan"),
            context={"request": SimpleNamespace(user=self.finance_user)},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

        with patch(
            "finance.models.LoanInstallment.objects.bulk_create",
            side_effect=RuntimeError("bulk insert failed"),
        ):
            with self.assertRaises(RuntimeError):
                serializer.save()

        self.assertFalse(Loan.objects.filter(name="Broken loan").exists())

    def test_rejects_sales_offer_installment_sequence_not_in_payment_terms(self):
        self.client.force_authenticate(self.finance_user)
        offer = self._sales_offer_with_two_installments()

        response = self.client.post(
            f"/finance/offer-installments/{offer.id}/3/mark-received/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SalesOfferInstallmentReceipt.objects.count(), 0)

    def test_allows_sales_offer_installment_sequence_in_payment_terms(self):
        self.client.force_authenticate(self.finance_user)
        offer = self._sales_offer_with_two_installments()

        response = self.client.post(
            f"/finance/offer-installments/{offer.id}/2/mark-received/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        receipt = SalesOfferInstallmentReceipt.objects.get()
        self.assertEqual(receipt.sequence, 2)
        self.assertTrue(receipt.is_received)

    @staticmethod
    def _loan_payload(name="Term loan"):
        return {
            "name": name,
            "principal": "1200.00",
            "interest_rate": "0.0000",
            "term_months": 2,
            "currency": "EUR",
            "first_payment_date": date(2026, 1, 1).isoformat(),
            "notes": "",
        }

    @staticmethod
    def _sales_offer_with_two_installments():
        customer = Customer.objects.create(code="C-001", name="Test Customer")
        terms = PaymentTerms.objects.create(
            name="Split",
            code="split",
            default_lines=[
                {"percentage": "50.00", "label": "Advance"},
                {"percentage": "50.00", "label": "Balance"},
            ],
        )
        return SalesOffer.objects.create(
            offer_no="OF-2026-0001",
            customer=customer,
            title="Offer",
            payment_terms=terms,
        )
