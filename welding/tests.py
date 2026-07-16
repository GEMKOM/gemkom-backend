from unittest.mock import patch

from django.test import TestCase

from welding.management.commands.drain_welding_cost_queue import Command


class _LockedQueueManager:
    """Minimal queryset double that always exposes one locked queue row."""

    def __init__(self):
        self.exclusions = []
        self.current_exclusions = set()

    def exclude(self, *, job_no__in):
        self.current_exclusions = set(job_no__in)
        self.exclusions.append(self.current_exclusions)
        return self

    def order_by(self, *args):
        return self

    def values_list(self, *args, **kwargs):
        return self

    def __getitem__(self, key):
        return [] if "JOB-1" in self.current_exclusions else ["JOB-1"]

    def select_for_update(self, **kwargs):
        return self

    def filter(self, **kwargs):
        return self

    def first(self):
        return None


class DrainWeldingCostQueueTests(TestCase):
    def test_locked_row_is_not_selected_repeatedly(self):
        manager = _LockedQueueManager()

        with (
            patch(
                "welding.management.commands.drain_welding_cost_queue."
                "WeldingJobCostRecalcQueue.objects",
                manager,
            ),
            patch(
                "welding.management.commands.drain_welding_cost_queue."
                "transaction.atomic",
            ),
        ):
            Command().handle(batch=100)

        self.assertEqual(manager.exclusions, [set(), {"JOB-1"}])
