from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from planning.models import PlanningRequest

User = get_user_model()

REQUESTS_URL = '/planning/requests/'


class PlanningRequestListScopingTests(TestCase):
    """The main list shows each user only their own planning requests;
    superusers see all. Detail views stay open for cross-team flows."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create(username='scope-admin', is_superuser=True)
        cls.user1 = User.objects.create(username='scope-planner-1')
        cls.user2 = User.objects.create(username='scope-planner-2')

        def pr(num, user, status=None):
            obj = PlanningRequest.objects.create(
                request_number=num, title='t', created_by=user)
            if status:
                # Bypass save(): the model derives status on create.
                PlanningRequest.objects.filter(pk=obj.pk).update(status=status)
                obj.refresh_from_db()
            return obj

        cls.pr1a = pr('PL-SC-1', cls.user1)
        cls.pr1b = pr('PL-SC-2', cls.user1, status='pending_erp_entry')
        cls.pr2 = pr('PL-SC-3', cls.user2)

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @staticmethod
    def _ids(resp):
        data = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        return {row['id'] for row in data}

    def test_regular_user_sees_only_own_requests(self):
        resp = self._client(self.user1).get(REQUESTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {self.pr1a.id, self.pr1b.id})

    def test_scoping_composes_with_filters(self):
        resp = self._client(self.user1).get(REQUESTS_URL, {'status': 'pending_erp_entry'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {self.pr1b.id})

        # Filtering by another creator can't leak their rows
        resp = self._client(self.user1).get(REQUESTS_URL, {'created_by': self.user2.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), set())

    def test_superuser_sees_all(self):
        resp = self._client(self.superuser).get(REQUESTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({self.pr1a.id, self.pr1b.id, self.pr2.id} <= self._ids(resp))

    def test_detail_stays_open_for_non_owners(self):
        # Other teams (procurement, warehouse) work with requests they didn't
        # create — retrieve is intentionally unscoped.
        resp = self._client(self.user1).get(f'{REQUESTS_URL}{self.pr2.id}/')
        self.assertEqual(resp.status_code, 200)
