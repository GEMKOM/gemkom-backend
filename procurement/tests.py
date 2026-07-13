from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from .models import (
    Item,
    ItemOffer,
    PurchaseRequest,
    PurchaseRequestItem,
    Supplier,
    SupplierOffer,
)
from .services import cancel_purchase_request, revise_purchase_request


class DBSUsageCancellationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='requestor')
        self.item = Item.objects.create(code='I-001', name='Steel plate', unit='adet')
        self.supplier = Supplier.objects.create(
            name='DBS Supplier',
            has_dbs=True,
            dbs_used=Decimal('100.00'),
            dbs_currency='TRY',
        )

    def _create_recommended_dbs_request(self, status):
        pr = PurchaseRequest.objects.create(
            title='Material request',
            requestor=self.user,
            status=status,
        )
        pr_item = PurchaseRequestItem.objects.create(
            purchase_request=pr,
            item=self.item,
            quantity=Decimal('10.00'),
        )
        supplier_offer = SupplierOffer.objects.create(
            purchase_request=pr,
            supplier=self.supplier,
            currency='TRY',
            tax_rate=Decimal('20.00'),
        )
        ItemOffer.objects.create(
            purchase_request_item=pr_item,
            supplier_offer=supplier_offer,
            unit_price=Decimal('5.00'),
            total_price=Decimal('50.00'),
            is_recommended=True,
        )
        return pr

    def test_revising_submitted_pr_does_not_reverse_unbooked_dbs_usage(self):
        pr = self._create_recommended_dbs_request(status='submitted')

        draft = revise_purchase_request(pr, self.user)

        self.assertIsNotNone(draft.pk)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.dbs_used, Decimal('100.00'))
        pr.refresh_from_db()
        self.assertEqual(pr.status, 'cancelled')

    def test_cancelling_approved_pr_reverses_booked_dbs_usage(self):
        pr = self._create_recommended_dbs_request(status='approved')

        cancel_purchase_request(pr, self.user)

        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.dbs_used, Decimal('40.00'))
