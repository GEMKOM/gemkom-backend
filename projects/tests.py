from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from projects.models import (
    Customer,
    JobOrder,
    JobOrderCostSummary,
    JobOrderDepartmentTask,
)
from projects.serializers import CostTableRowSerializer
from projects.services.costing import phase_share_amount
from projects.views import JobOrderDepartmentTaskViewSet
from sales.models import SalesOffer, SalesOfferItem, SalesOfferPriceRevision


class PhaseSellingPriceRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner')
        self.customer = Customer.objects.create(code='CUST', name='Customer')
        self.offer = SalesOffer.objects.create(
            offer_no='OF-2026-0001',
            customer=self.customer,
            title='Phased offer',
            delivery_date_requested=date(2026, 7, 1),
            pricing_mode='flat',
        )
        self.item = SalesOfferItem.objects.create(
            offer=self.offer,
            title_override='Product',
            quantity=4,
            unit_price=Decimal('25.00'),
        )
        self.price = SalesOfferPriceRevision.objects.create(
            offer=self.offer,
            revision_type='approved',
            amount=Decimal('100.00'),
            currency='EUR',
            approval_round=1,
            is_current=True,
        )
        self.root_job = JobOrder.objects.create(
            job_no='CUST-ROOT',
            title='Engineering root',
            customer=self.customer,
            created_by=self.user,
        )
        self.master_job = JobOrder.objects.create(
            job_no='CUST-01',
            title='Product',
            customer=self.customer,
            parent=self.root_job,
            quantity=4,
            source_offer=self.offer,
            source_offer_item=self.item,
            created_by=self.user,
        )
        self.phase_root = JobOrder.objects.create(
            job_no='CUST-ROOT/P1',
            title='Phase 1',
            customer=self.customer,
            parent=self.root_job,
            source_job_order=self.root_job,
            phase_number=1,
            created_by=self.user,
        )
        self.allocation = JobOrder.objects.create(
            job_no='CUST-01/P1',
            title='Product - P1',
            customer=self.customer,
            parent=self.phase_root,
            quantity=1,
            source_job_order=self.master_job,
            phase_number=1,
            source_offer=self.offer,
            source_offer_item=self.item,
            created_by=self.user,
        )
        JobOrderCostSummary.objects.create(
            job_order=self.allocation,
            estimated_total_cost=Decimal('0.00'),
        )

    def test_phase_share_amount_is_scaled_by_allocated_quantity(self):
        self.assertEqual(
            phase_share_amount(self.allocation, self.price.amount),
            Decimal('25.00'),
        )

    def test_cost_table_selling_price_uses_quantity_scaled_phase_share(self):
        serializer = CostTableRowSerializer(self.allocation)

        self.assertEqual(serializer.data['selling_price'], '25.00')


class DepartmentTaskDeleteRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='office')
        self.customer = Customer.objects.create(code='TASK', name='Task Customer')
        self.job_order = JobOrder.objects.create(
            job_no='TASK-01',
            title='Workflow Job',
            customer=self.customer,
            created_by=self.user,
        )
        self.factory = APIRequestFactory()
        self.destroy_view = JobOrderDepartmentTaskViewSet.as_view({'delete': 'destroy'})

    def _delete_task(self, task):
        request = self.factory.delete(f'/projects/department-tasks/{task.pk}/')
        force_authenticate(request, user=self.user)
        return self.destroy_view(request, pk=task.pk)

    def test_main_department_task_cannot_be_deleted(self):
        task = JobOrderDepartmentTask.objects.create(
            job_order=self.job_order,
            department='manufacturing',
            title='Welding',
            task_type='welding',
            created_by=self.user,
        )

        response = self._delete_task(task)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(JobOrderDepartmentTask.objects.filter(pk=task.pk).exists())

    def test_part_subtask_can_still_be_deleted(self):
        parent = JobOrderDepartmentTask.objects.create(
            job_order=self.job_order,
            department='manufacturing',
            title='Manufacturing',
            task_type='welding',
            created_by=self.user,
        )
        subtask = JobOrderDepartmentTask.objects.create(
            job_order=self.job_order,
            department='manufacturing',
            parent=parent,
            title='Part 1',
            task_type='part',
            created_by=self.user,
        )

        response = self._delete_task(subtask)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(JobOrderDepartmentTask.objects.filter(pk=subtask.pk).exists())
