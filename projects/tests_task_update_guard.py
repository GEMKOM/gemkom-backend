from django.test import SimpleTestCase

from projects.models import JobOrderDepartmentTask
from projects.serializers import DepartmentTaskUpdateSerializer


class TerminalTaskUpdateGuardTests(SimpleTestCase):
    """Completed/skipped tasks accept weight + target-date edits, nothing else."""

    def _validate(self, status, data):
        task = JobOrderDepartmentTask(status=status)
        serializer = DepartmentTaskUpdateSerializer(instance=task, data=data, partial=True)
        return serializer.is_valid(), serializer.errors

    def test_target_dates_editable_on_completed(self):
        ok, errors = self._validate('completed', {
            'target_start_date': '2026-07-01',
            'target_completion_date': '2026-07-10',
        })
        self.assertTrue(ok, errors)

    def test_target_dates_clearable_on_completed(self):
        ok, errors = self._validate('completed', {'target_completion_date': None})
        self.assertTrue(ok, errors)

    def test_weight_still_editable_on_completed(self):
        ok, errors = self._validate('completed', {'weight': 5})
        self.assertTrue(ok, errors)

    def test_other_fields_still_blocked_on_completed(self):
        ok, _ = self._validate('completed', {'title': 'Yeni başlık'})
        self.assertFalse(ok)

    def test_mixed_payload_still_blocked_on_completed(self):
        ok, _ = self._validate('completed', {
            'target_start_date': '2026-07-01',
            'title': 'Yeni başlık',
        })
        self.assertFalse(ok)

    def test_target_dates_editable_on_skipped(self):
        ok, errors = self._validate('skipped', {'target_completion_date': '2026-07-10'})
        self.assertTrue(ok, errors)

    def test_open_tasks_unaffected(self):
        ok, errors = self._validate('in_progress', {'title': 'Yeni başlık'})
        self.assertTrue(ok, errors)
