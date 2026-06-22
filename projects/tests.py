from django.test import TestCase

from projects.models import Customer, JobOrder
from projects.services.phases import create_phases


class CreatePhasesTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(code='270', name='ACME')
        self.root = JobOrder.objects.create(
            job_no='270-01',
            title='Root job',
            customer=self.customer,
        )
        self.product = JobOrder.objects.create(
            job_no='270-01-01',
            title='Product job',
            customer=self.customer,
            parent=self.root,
            quantity=2,
        )

    def test_rejects_cumulative_allocation_over_product_quantity(self):
        create_phases(
            self.root,
            phases=[
                {'phase_number': 1, 'title': 'P1'},
                {'phase_number': 2, 'title': 'P2'},
            ],
            allocations=[
                {'product_job_no': self.product.job_no, 'quantities': {1: 1, 2: 1}},
            ],
        )

        with self.assertRaisesMessage(ValueError, 'ürün miktarına (2) eşit olmalıdır'):
            create_phases(
                self.root,
                phases=[{'phase_number': 3, 'title': 'P3'}],
                allocations=[
                    {'product_job_no': self.product.job_no, 'quantities': {3: 2}},
                ],
            )

        self.assertFalse(JobOrder.objects.filter(job_no='270-01/P3').exists())
        self.assertEqual(self.product.phase_mirrors.count(), 2)

    def test_rejects_duplicate_product_allocation_entries(self):
        with self.assertRaisesMessage(ValueError, 'birden fazla kez'):
            create_phases(
                self.root,
                phases=[
                    {'phase_number': 1, 'title': 'P1'},
                    {'phase_number': 2, 'title': 'P2'},
                ],
                allocations=[
                    {'product_job_no': self.product.job_no, 'quantities': {1: 2}},
                    {'product_job_no': self.product.job_no, 'quantities': {2: 2}},
                ],
            )

        self.assertFalse(JobOrder.objects.filter(job_no='270-01/P1').exists())
