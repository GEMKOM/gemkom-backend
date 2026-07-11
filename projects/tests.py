from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import CurrencyRateSnapshot
from planning.models import PlanningRequest, PlanningRequestItem
from procurement.models import Item
from .models import Customer, JobOrder, JobOrderCostSummary
from .serializers import ProcurementLinesSubmitSerializer
from .services import costing


class ProcurementLineValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cost-user', password='pw')
        self.customer = Customer.objects.create(code='CUST', name='Customer')
        self.job_a = JobOrder.objects.create(
            job_no='JOB-A',
            title='Job A',
            customer=self.customer,
        )
        self.job_b = JobOrder.objects.create(
            job_no='JOB-B',
            title='Job B',
            customer=self.customer,
        )
        self.item = Item.objects.create(code='ITEM-1', name='Steel', unit='adet')
        self.planning_request = PlanningRequest.objects.create(
            request_number='PR-1',
            title='Planning',
            created_by=self.user,
        )
        self.foreign_planning_item = PlanningRequestItem.objects.create(
            planning_request=self.planning_request,
            item=self.item,
            job_no=self.job_b.job_no,
            quantity=Decimal('1.00'),
        )

    def test_submit_rejects_planning_item_from_another_job(self):
        serializer = ProcurementLinesSubmitSerializer(data={
            'job_order': self.job_a.job_no,
            'lines': [{
                'item': self.item.id,
                'quantity': '1.00',
                'unit_price': '10.000000',
                'planning_request_item': self.foreign_planning_item.id,
            }],
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('lines', serializer.errors)


class GeneralExpensesCostingTests(TestCase):
    def test_general_expenses_rate_is_converted_from_try_to_eur(self):
        costing._fetch_rates.cache_clear()
        CurrencyRateSnapshot.objects.create(
            date=date.today(),
            rates={'EUR': '0.025', 'USD': '0.90'},
        )
        customer = Customer.objects.create(code='FX', name='FX Customer')
        job_order = JobOrder.objects.create(
            job_no='JOB-FX',
            title='FX Job',
            customer=customer,
            total_weight_kg=Decimal('100.00'),
            general_expenses_rate=Decimal('0.7000'),
        )

        costing.recompute_job_cost_summary(job_order.job_no)
        summary = JobOrderCostSummary.objects.get(job_order=job_order)
        payload = costing.build_job_cost_payload(job_order)

        self.assertEqual(summary.general_expenses_cost, Decimal('1.75'))
        self.assertEqual(payload['estimated']['components']['general_expenses_cost'], '1.75')
