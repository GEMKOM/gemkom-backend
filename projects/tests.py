from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Customer, JobOrder, JobOrderDepartmentTask


class DepartmentTaskDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='planner', password='password')
        self.client.force_authenticate(self.user)
        self.customer = Customer.objects.create(
            code='CUST',
            name='Customer',
        )
        self.job_order = JobOrder.objects.create(
            job_no='270-01',
            title='Root job',
            customer=self.customer,
            status='active',
        )

    def _task(self, **kwargs):
        defaults = {
            'job_order': self.job_order,
            'department': 'design',
            'title': 'Task',
            'weight': 10,
        }
        defaults.update(kwargs)
        return JobOrderDepartmentTask.objects.create(**defaults)

    def test_main_department_task_cannot_be_deleted(self):
        main_task = self._task(title='Design')

        response = self.client.delete(f'/projects/department-tasks/{main_task.pk}/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(JobOrderDepartmentTask.objects.filter(pk=main_task.pk).exists())

    def test_non_part_subtask_cannot_be_deleted(self):
        parent = self._task(title='Manufacturing', department='manufacturing')
        subtask = self._task(
            title='Welding',
            department='manufacturing',
            parent=parent,
            task_type='welding',
        )

        response = self.client.delete(f'/projects/department-tasks/{subtask.pk}/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(JobOrderDepartmentTask.objects.filter(pk=subtask.pk).exists())

    def test_part_subtask_can_still_be_deleted(self):
        parent = self._task(title='Manufacturing', department='manufacturing')
        subtask = self._task(
            title='Part 1',
            department='manufacturing',
            parent=parent,
            task_type='part',
        )

        response = self.client.delete(f'/projects/department-tasks/{subtask.pk}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(JobOrderDepartmentTask.objects.filter(pk=subtask.pk).exists())
