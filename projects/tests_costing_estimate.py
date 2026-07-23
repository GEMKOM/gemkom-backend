from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from projects.models import Customer, JobOrder
from projects.services.meeting_brief import _delivered_uncosted_material

User = get_user_model()


class DeliveredUncostedMaterialTests(TestCase):
    """The meeting verdict subtracts offer/historical-priced material for
    DELIVERED items with no real cost from its projected cost — the stored
    estimate itself stays untouched (user decision). Regression for 293-04,
    where a delivered-from-stock item carried a fictional 1000 EUR offer
    price into the Finansal verdict."""

    @classmethod
    def setUpTestData(cls):
        from planning.models import PlanningRequest, PlanningRequestItem
        from procurement.models import Item

        user = User.objects.create(username='cost-est-user')
        customer = Customer.objects.create(code='C-CE', name='Cost Customer')
        JobOrder.objects.create(job_no='950-01', title='Estimate', customer=customer)
        item = Item.objects.create(code='CE-1', name='Sac', unit='kg')
        planning_request = PlanningRequest.objects.create(
            request_number='PL-CE-1', title='t', created_by=user)

        def pri(qty, delivered):
            return PlanningRequestItem.objects.create(
                planning_request=planning_request, item=item, job_no='950-01',
                quantity=Decimal(qty), is_delivered=delivered)

        cls.pri_delivered_offer = pri('10', True)   # counts: fictional offer price
        cls.pri_delivered_po = pri('5', True)       # real PO price -> not fictional
        cls.pri_open_offer = pri('7', False)        # not delivered -> untouched

    def test_only_delivered_offer_priced_items_count(self):
        def price(source, unit):
            return {
                'price_source': source,
                'unit_price_eur': Decimal(unit),
                'price_date': None,
                'original_unit_price': Decimal(unit),
                'original_currency': 'EUR',
            }

        prices = {
            self.pri_delivered_offer.pk: price('recommended_offer', '100'),
            self.pri_delivered_po.pk: price('po_line', '2'),
            self.pri_open_offer.pk: price('any_offer', '3'),
        }
        with mock.patch('planning.price_utils.resolve_planning_item_price',
                        side_effect=lambda pri: prices[pri.pk]):
            adjustment = _delivered_uncosted_material(['950-01'])

        # Only the delivered offer-priced item: 10 x 100
        self.assertEqual(adjustment, Decimal('1000'))
