from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from planning.models import PlanningRequest, PlanningRequestItem
from procurement.models import Item

User = get_user_model()

REQUESTS_URL = '/planning/requests/'
MY_REQUESTS_URL = '/planning/requests/my_requests/'
ITEMS_URL = '/planning/items/'


class PlanningRequestListScopingTests(TestCase):
    """The plain list is shared across teams (planning management, warehouse
    inventory allocation, department-request lookups), so it is NOT scoped by
    creator — every authenticated user sees every request. The `my_requests`
    action is the own-only view."""

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

    def test_regular_user_sees_all_requests_on_list(self):
        # The plain list is unscoped: other teams work with requests they did
        # not create (warehouse allocation, procurement, cross-team lookups).
        resp = self._client(self.user1).get(REQUESTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({self.pr1a.id, self.pr1b.id, self.pr2.id} <= self._ids(resp))

    def test_created_by_filter_still_available(self):
        # Callers that want a per-user view can still opt in via the query param.
        resp = self._client(self.user1).get(REQUESTS_URL, {'created_by': self.user2.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {self.pr2.id})

    def test_my_requests_returns_only_own(self):
        # The dedicated own-only endpoint is the way to scope by creator.
        resp = self._client(self.user1).get(MY_REQUESTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), {self.pr1a.id, self.pr1b.id})

    def test_superuser_sees_all(self):
        resp = self._client(self.superuser).get(REQUESTS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({self.pr1a.id, self.pr1b.id, self.pr2.id} <= self._ids(resp))

    def test_detail_stays_open_for_non_owners(self):
        # Other teams (procurement, warehouse) work with requests they didn't
        # create — retrieve is intentionally unscoped.
        resp = self._client(self.user1).get(f'{REQUESTS_URL}{self.pr2.id}/')
        self.assertEqual(resp.status_code, 200)


class PlanningRequestItemMineFilterTests(TestCase):
    """The /planning/items/ list is unscoped by default (shared across teams).
    The CNC cut-create modal opts in with ?mine=true to show each user only
    plate items from their own planning requests; superusers still see all."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create(username='item-admin', is_superuser=True)
        cls.user1 = User.objects.create(username='item-planner-1')
        cls.user2 = User.objects.create(username='item-planner-2')

        cls.plate = Item.objects.create(
            code='0100 0000 0005 000 000', name='5 mm ST 37-2 SAC', unit='kg')

        def item_for(user, num):
            pr = PlanningRequest.objects.create(
                request_number=num, title='t', created_by=user)
            return PlanningRequestItem.objects.create(
                planning_request=pr, item=cls.plate,
                job_no='900-01', quantity=Decimal('500'))

        cls.item_u1 = item_for(cls.user1, 'PL-IT-1')
        cls.item_u2 = item_for(cls.user2, 'PL-IT-2')

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @staticmethod
    def _ids(resp):
        data = resp.data['results'] if isinstance(resp.data, dict) and 'results' in resp.data else resp.data
        return {row['id'] for row in data}

    def test_list_unscoped_by_default(self):
        resp = self._client(self.user1).get(ITEMS_URL, {'fields': 'simple'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({self.item_u1.id, self.item_u2.id} <= self._ids(resp))

    def test_mine_scopes_to_own_requests(self):
        resp = self._client(self.user1).get(ITEMS_URL, {'fields': 'simple', 'mine': 'true'})
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(self.item_u1.id, ids)
        self.assertNotIn(self.item_u2.id, ids)

    def test_mine_is_noop_for_superuser(self):
        resp = self._client(self.superuser).get(ITEMS_URL, {'fields': 'simple', 'mine': 'true'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue({self.item_u1.id, self.item_u2.id} <= self._ids(resp))
