from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.contrib.auth.models import User
from decimal import Decimal
from planning.models import PlanningRequest, PlanningRequestItem
from procurement.models import Item, PurchaseRequest


class _RelatedList:
    def __init__(self, *items):
        self._items = list(items)

    def all(self):
        return list(self._items)


class PriceResolutionTestCase(SimpleTestCase):
    def _currency_passthrough(self, amount, currency, ref_date):
        return amount

    @patch('projects.services.costing.convert_to_eur')
    def test_po_line_price_is_not_reduced_by_tax(self, convert_to_eur):
        convert_to_eur.side_effect = self._currency_passthrough
        from planning.price_utils import resolve_planning_item_price

        created_at = datetime(2026, 6, 1, 12, 0, 0)
        po = SimpleNamespace(
            status='awaiting_payment',
            tax_rate=Decimal('20.00'),
            currency='EUR',
            ordered_at=None,
            created_at=created_at,
        )
        po_line = SimpleNamespace(unit_price=Decimal('120.00'), po=po)
        purchase_request = SimpleNamespace(status='approved')
        purchase_request_item = SimpleNamespace(
            purchase_request=purchase_request,
            po_lines=_RelatedList(po_line),
            offers=_RelatedList(),
        )
        planning_item = SimpleNamespace(
            purchase_request_items=_RelatedList(purchase_request_item),
        )

        result = resolve_planning_item_price(planning_item)

        self.assertEqual(result['unit_price_eur'], Decimal('120.00'))
        self.assertEqual(result['original_unit_price'], Decimal('120.00'))
        convert_to_eur.assert_called_once_with(Decimal('120.00'), 'EUR', created_at.date())

    @patch('projects.services.costing.convert_to_eur')
    def test_offer_price_is_not_reduced_by_tax(self, convert_to_eur):
        convert_to_eur.side_effect = self._currency_passthrough
        from planning.price_utils import resolve_planning_item_price

        created_at = datetime(2026, 6, 2, 12, 0, 0)
        supplier_offer = SimpleNamespace(
            tax_rate=Decimal('20.00'),
            currency='EUR',
            created_at=created_at,
        )
        offer = SimpleNamespace(
            unit_price=Decimal('90.00'),
            supplier_offer=supplier_offer,
            is_recommended=True,
        )
        purchase_request = SimpleNamespace(status='approved')
        purchase_request_item = SimpleNamespace(
            purchase_request=purchase_request,
            po_lines=_RelatedList(),
            offers=_RelatedList(offer),
        )
        planning_item = SimpleNamespace(
            purchase_request_items=_RelatedList(purchase_request_item),
        )

        result = resolve_planning_item_price(planning_item)

        self.assertEqual(result['unit_price_eur'], Decimal('90.00'))
        self.assertEqual(result['original_unit_price'], Decimal('90.00'))
        convert_to_eur.assert_called_once_with(Decimal('90.00'), 'EUR', created_at.date())

    @patch('projects.services.costing.convert_to_eur')
    def test_annotated_po_line_price_is_not_reduced_by_tax(self, convert_to_eur):
        convert_to_eur.side_effect = self._currency_passthrough
        from planning.price_utils import resolve_planning_item_price

        price_date = datetime(2026, 6, 3, 12, 0, 0)
        planning_item = SimpleNamespace(
            purchase_request_items=_RelatedList(),
            _t2_price=Decimal('240.00'),
            _t2_currency='EUR',
            _t2_tax=Decimal('20.00'),
            _t2_date=price_date,
        )

        result = resolve_planning_item_price(planning_item)

        self.assertEqual(result['unit_price_eur'], Decimal('240.00'))
        self.assertEqual(result['original_unit_price'], Decimal('240.00'))
        convert_to_eur.assert_called_once_with(Decimal('240.00'), 'EUR', price_date.date())


class PlanningRequestCompletionTestCase(TestCase):
    """Test the completion logic for PlanningRequest"""

    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(username='testuser', password='testpass')

        # Create test items
        self.item1 = Item.objects.create(
            code='ITEM001',
            name='Test Item 1',
            unit_price=Decimal('100.00'),
            stock_quantity=Decimal('50.00')
        )
        self.item2 = Item.objects.create(
            code='ITEM002',
            name='Test Item 2',
            unit_price=Decimal('200.00'),
            stock_quantity=Decimal('30.00')
        )

        # Create planning request
        self.planning_request = PlanningRequest.objects.create(
            title='Test Planning Request',
            created_by=self.user,
            status='ready'
        )

    def test_completion_with_all_items_from_inventory(self):
        """Test completion when all items have quantity_to_purchase = 0"""
        # Create items with quantity_to_purchase = 0 (all from inventory)
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_from_inventory=Decimal('10.00'),
            quantity_to_purchase=Decimal('0.00')
        )
        item2 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item2,
            job_no='JOB002',
            quantity=Decimal('5.00'),
            quantity_from_inventory=Decimal('5.00'),
            quantity_to_purchase=Decimal('0.00')
        )

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is completed
        self.assertTrue(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'completed')
        self.assertIsNotNone(self.planning_request.completed_at)

    def test_completion_with_all_items_approved(self):
        """Test completion when all items have approved purchase requests"""
        # Create items with quantity_to_purchase > 0
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_to_purchase=Decimal('10.00')
        )
        item2 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item2,
            job_no='JOB002',
            quantity=Decimal('5.00'),
            quantity_to_purchase=Decimal('5.00')
        )

        # Create approved purchase requests for both items
        pr1 = PurchaseRequest.objects.create(
            title='Purchase Request 1',
            requestor=self.user,
            status='approved'
        )
        pr1.planning_request_items.add(item1)

        pr2 = PurchaseRequest.objects.create(
            title='Purchase Request 2',
            requestor=self.user,
            status='approved'
        )
        pr2.planning_request_items.add(item2)

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is completed
        self.assertTrue(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'completed')
        self.assertIsNotNone(self.planning_request.completed_at)

    def test_completion_with_mixed_items(self):
        """Test completion with mix of inventory and approved purchase requests"""
        # Create item 1 with all from inventory (quantity_to_purchase = 0)
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_from_inventory=Decimal('10.00'),
            quantity_to_purchase=Decimal('0.00')
        )

        # Create item 2 with quantity to purchase
        item2 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item2,
            job_no='JOB002',
            quantity=Decimal('5.00'),
            quantity_to_purchase=Decimal('5.00')
        )

        # Create approved purchase request for item 2
        pr = PurchaseRequest.objects.create(
            title='Purchase Request',
            requestor=self.user,
            status='approved'
        )
        pr.planning_request_items.add(item2)

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is completed
        self.assertTrue(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'completed')
        self.assertIsNotNone(self.planning_request.completed_at)

    def test_not_completed_with_pending_items(self):
        """Test that planning request is NOT completed when items are still pending"""
        # Create items with quantity_to_purchase > 0 but no approved purchase requests
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_to_purchase=Decimal('10.00')
        )
        item2 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item2,
            job_no='JOB002',
            quantity=Decimal('5.00'),
            quantity_to_purchase=Decimal('5.00')
        )

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is NOT completed
        self.assertFalse(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'ready')
        self.assertIsNone(self.planning_request.completed_at)

    def test_not_completed_with_submitted_purchase_request(self):
        """Test that planning request is NOT completed when purchase request is only submitted"""
        # Create item with quantity_to_purchase > 0
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_to_purchase=Decimal('10.00')
        )

        # Create submitted (not approved) purchase request
        pr = PurchaseRequest.objects.create(
            title='Purchase Request',
            requestor=self.user,
            status='submitted'  # Not approved yet
        )
        pr.planning_request_items.add(item1)

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is NOT completed
        self.assertFalse(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'ready')
        self.assertIsNone(self.planning_request.completed_at)

    def test_completion_with_partial_inventory_and_approved_pr(self):
        """Test completion when one item has partial inventory allocation and approved PR"""
        # Create item with partial inventory (some from inventory, some to purchase)
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('20.00'),
            quantity_from_inventory=Decimal('10.00'),
            quantity_to_purchase=Decimal('10.00')  # Remaining needs to be purchased
        )

        # Create item with all from inventory
        item2 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item2,
            job_no='JOB002',
            quantity=Decimal('5.00'),
            quantity_from_inventory=Decimal('5.00'),
            quantity_to_purchase=Decimal('0.00')
        )

        # Create approved purchase request for item1's remaining quantity
        pr = PurchaseRequest.objects.create(
            title='Purchase Request',
            requestor=self.user,
            status='approved'
        )
        pr.planning_request_items.add(item1)

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert planning request is completed
        self.assertTrue(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'completed')
        self.assertIsNotNone(self.planning_request.completed_at)

    def test_already_completed_returns_false(self):
        """Test that check_and_update_completion_status returns False if already completed"""
        # Create item from inventory
        item1 = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item1,
            job_no='JOB001',
            quantity=Decimal('10.00'),
            quantity_to_purchase=Decimal('0.00')
        )

        # Mark as completed
        self.planning_request.status = 'completed'
        self.planning_request.save()

        # Check completion status
        result = self.planning_request.check_and_update_completion_status()

        # Assert returns False (no status change)
        self.assertFalse(result)

    def test_no_items_returns_false(self):
        """Test that planning request without items returns False"""
        # Check completion status without items
        result = self.planning_request.check_and_update_completion_status()

        # Assert returns False
        self.assertFalse(result)
        self.planning_request.refresh_from_db()
        self.assertEqual(self.planning_request.status, 'ready')
