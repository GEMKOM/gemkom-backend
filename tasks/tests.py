from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from planning.models import DepartmentRequest
from .models import Operation, Part


class ConvertedPartLockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('planner', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.department_request = DepartmentRequest.objects.create(
            title='Locked parts',
            department='manufacturing',
            requestor=self.user,
        )
        self.part = Part.objects.create(
            key='PT-LOCKED',
            name='Locked part',
            job_no='JOB-LOCKED',
            quantity=1,
            department_request=self.department_request,
        )
        self.operation = Operation.objects.create(
            part=self.part,
            name='Locked operation',
            order=1,
            created_by=self.user,
            created_at=1,
            completion_date=123,
            completed_by=self.user,
        )

    def test_locked_part_cannot_be_patched_or_unlinked(self):
        response = self.client.patch(
            f'/tasks/parts/{self.part.key}/',
            {'name': 'Changed', 'department_request': None},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, 'Locked part')
        self.assertEqual(self.part.department_request_id, self.department_request.id)

    def test_locked_operation_cannot_be_unmarked_or_planned(self):
        unmark_response = self.client.post(
            f'/tasks/operations/{self.operation.key}/unmark_completed/',
            format='json',
        )
        bulk_plan_response = self.client.put(
            '/tasks/operations/planning/bulk-save/',
            [{'key': self.operation.key, 'in_plan': True, 'plan_order': 1}],
            format='json',
        )

        self.assertEqual(unmark_response.status_code, 400)
        self.assertEqual(bulk_plan_response.status_code, 400)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.completion_date, 123)
        self.assertFalse(self.operation.in_plan)
