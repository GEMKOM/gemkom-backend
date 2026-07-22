from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework import serializers

from overtime.models import OvertimeEntry, OvertimeRequest
from overtime.serializers import raise_if_overtime_clash

User = get_user_model()


class OvertimeOverlapGuardTests(TestCase):
    """
    The same person may not sit on two overlapping overtime requests — but a
    person *rejected* from a request is not working it, so that slot is free
    again. Regression guard: the check used to match on the entry's user without
    looking at its status, which permanently blocked anyone who had ever been
    retracted from an overlapping request.
    """

    def setUp(self):
        self.start = timezone.now().replace(microsecond=0) + timedelta(days=1)
        self.end = self.start + timedelta(hours=4)
        self.requester = User.objects.create(username="requester")
        self.worker = User.objects.create(username="worker")
        self.other = User.objects.create(username="other")

        self.existing = OvertimeRequest.objects.create(
            requester=self.requester,
            start_at=self.start,
            end_at=self.end,
            status="approved",
        )

    def _entry(self, user, status):
        return OvertimeEntry.objects.create(
            request=self.existing, user=user, job_no="X-1", status=status
        )

    def _check(self, users, start=None, end=None, exclude_pk=None):
        raise_if_overtime_clash(
            start_at=start or self.start,
            end_at=end or self.end,
            users=users,
            exclude_pk=exclude_pk,
        )

    # --- the bug ---------------------------------------------------------

    def test_rejected_user_may_be_rebooked_in_same_window(self):
        self._entry(self.worker, "rejected")
        self._check([self.worker])  # must not raise

    def test_rejected_user_rebookable_even_when_others_still_on_request(self):
        self._entry(self.worker, "rejected")
        self._entry(self.other, "approved")
        self._check([self.worker])  # only the rejected person is being re-booked

    # --- behaviour that must NOT regress ---------------------------------

    def test_approved_user_still_blocked(self):
        self._entry(self.worker, "approved")
        with self.assertRaises(serializers.ValidationError):
            self._check([self.worker])

    def test_pending_user_still_blocked(self):
        # Entries predate per-entry decisions and carry the default 'pending';
        # those people are still booked.
        self._entry(self.worker, "pending")
        with self.assertRaises(serializers.ValidationError):
            self._check([self.worker])

    def test_blocked_when_only_one_of_several_users_clashes(self):
        self._entry(self.worker, "rejected")
        self._entry(self.other, "approved")
        with self.assertRaises(serializers.ValidationError):
            self._check([self.worker, self.other])

    def test_error_names_the_clashing_user_and_request(self):
        self._entry(self.worker, "approved")
        with self.assertRaises(serializers.ValidationError) as ctx:
            self._check([self.worker])
        message = str(ctx.exception)
        self.assertIn("worker", message)
        self.assertIn(str(self.existing.pk), message)

    def test_cancelled_and_rejected_requests_do_not_block(self):
        self._entry(self.worker, "approved")
        for status in ("cancelled", "rejected"):
            OvertimeRequest.objects.filter(pk=self.existing.pk).update(status=status)
            self._check([self.worker])

    def test_non_overlapping_window_does_not_block(self):
        self._entry(self.worker, "approved")
        later = self.end + timedelta(hours=1)
        self._check([self.worker], start=later, end=later + timedelta(hours=2))

    def test_touching_windows_do_not_block(self):
        # Overlap is strict: a request ending exactly when the next starts is fine.
        self._entry(self.worker, "approved")
        self._check([self.worker], start=self.end, end=self.end + timedelta(hours=2))

    def test_editing_the_same_request_ignores_itself(self):
        self._entry(self.worker, "approved")
        self._check([self.worker], exclude_pk=self.existing.pk)
