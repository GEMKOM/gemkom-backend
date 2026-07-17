from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework import status

from welding.models import WeldingPlanAllocation
from welding.views import WeldingPlanAllocationViewSet


class WeldingPlanAllocationConcurrencyTests(SimpleTestCase):
    def setUp(self):
        self.request = SimpleNamespace(user=Mock(), data={})
        self.view = WeldingPlanAllocationViewSet()
        self.view.request = self.request

    @patch('welding.views.transaction.atomic')
    @patch('welding.views.get_object_or_404')
    def test_promote_rechecks_state_under_row_lock(self, get_object_or_404, atomic):
        stale_allocation = SimpleNamespace(pk=17, is_promoted=False)
        locked_allocation = SimpleNamespace(pk=17, is_promoted=True)
        self.view.get_object = Mock(return_value=stale_allocation)
        get_object_or_404.return_value = locked_allocation

        response = self.view.promote(self.request, pk=17)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        locked_queryset = get_object_or_404.call_args.args[0]
        self.assertTrue(locked_queryset.query.select_for_update)
        get_object_or_404.assert_called_once_with(locked_queryset, pk=17)
        atomic.assert_called_once_with()

    @patch('welding.views.transaction.atomic')
    @patch('welding.views.get_object_or_404')
    def test_destroy_rechecks_promoted_state_under_row_lock(self, get_object_or_404, atomic):
        stale_allocation = SimpleNamespace(pk=23, is_promoted=False)
        locked_allocation = SimpleNamespace(pk=23, is_promoted=True)
        self.view.get_object = Mock(return_value=stale_allocation)
        self.view.perform_destroy = Mock()
        get_object_or_404.return_value = locked_allocation

        response = self.view.destroy(self.request, pk=23)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        locked_queryset = get_object_or_404.call_args.args[0]
        self.assertTrue(locked_queryset.query.select_for_update)
        get_object_or_404.assert_called_once_with(locked_queryset, pk=23)
        self.view.perform_destroy.assert_not_called()
        atomic.assert_called_once_with()
