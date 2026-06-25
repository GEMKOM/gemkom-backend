from django.contrib.auth.models import User
from django.test import TestCase

from rest_framework import status
from rest_framework.test import APIClient

from machines.models import Machine


class MachinePermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.operator = User.objects.create_user(
            username='operator',
            password='password',
        )
        self.admin = User.objects.create_user(
            username='admin',
            password='password',
            is_staff=True,
        )
        self.machine = Machine.objects.create(
            name='Existing machine',
            machine_type='VM',
            used_in='machining',
        )

    def test_non_admin_cannot_mutate_machine_registry(self):
        self.client.force_authenticate(self.operator)

        create_response = self.client.post('/machines/', {
            'name': 'Unauthorized machine',
            'machine_type': 'VM',
            'used_in': 'machining',
            'properties': {},
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        update_response = self.client.patch(
            f'/machines/{self.machine.pk}/',
            {'name': 'Tampered machine'},
            format='json',
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

        delete_response = self.client.delete(f'/machines/{self.machine.pk}/')
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

        self.machine.refresh_from_db()
        self.assertEqual(self.machine.name, 'Existing machine')
        self.assertFalse(Machine.objects.filter(name='Unauthorized machine').exists())

    def test_admin_can_update_machine_registry(self):
        self.client.force_authenticate(self.admin)

        response = self.client.patch(
            f'/machines/{self.machine.pk}/',
            {'name': 'Updated machine'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.name, 'Updated machine')
