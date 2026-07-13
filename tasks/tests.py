from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from planning.models import DepartmentRequest

from .models import Operation, Part


class LockedPartAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='operator')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.department_request = DepartmentRequest.objects.create(
            title='Converted part request',
            department='Welding',
            requestor=self.user,
        )
        self.part = Part.objects.create(
            key='P-LOCKED',
            name='Locked part',
            department_request=self.department_request,
        )
        self.operation = Operation.objects.create(
            part=self.part,
            name='Locked operation',
            order=1,
        )

    def test_locked_part_cannot_be_updated_or_deleted(self):
        patch_response = self.client.patch(
            f'/tasks/parts/{self.part.key}/',
            {'name': 'Mutated part'},
            format='json',
        )
        delete_response = self.client.delete(f'/tasks/parts/{self.part.key}/')

        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, 'Locked part')

    def test_locked_part_operation_cannot_be_updated_or_deleted(self):
        patch_response = self.client.patch(
            f'/tasks/operations/{self.operation.key}/',
            {'name': 'Mutated operation'},
            format='json',
        )
        delete_response = self.client.delete(f'/tasks/operations/{self.operation.key}/')

        self.assertEqual(patch_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.name, 'Locked operation')
