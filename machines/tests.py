from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from machines.models import Machine


User = get_user_model()


class MachinePermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='operator', password='pw')
        self.client.force_authenticate(user=self.user)
        self.machine = Machine.objects.create(
            name='Horizontal Mill',
            machine_type='HM',
            used_in='machining',
        )

    def test_authenticated_user_can_read_machines(self):
        list_response = self.client.get('/machines/')
        detail_response = self.client.get(f'/machines/{self.machine.pk}/')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)

    def test_non_admin_cannot_create_machine(self):
        response = self.client.post('/machines/', {
            'name': 'Unauthorized Machine',
            'machine_type': 'HM',
            'used_in': 'machining',
        })

        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_update_machine(self):
        response = self.client.patch(
            f'/machines/{self.machine.pk}/',
            {'name': 'Tampered'},
            format='json',
        )

        self.assertEqual(response.status_code, 403)
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.name, 'Horizontal Mill')

    def test_non_admin_cannot_delete_machine(self):
        response = self.client.delete(f'/machines/{self.machine.pk}/')

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Machine.objects.filter(pk=self.machine.pk).exists())
