from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Customer, JobOrder, TechnicalDrawingRelease


class TechnicalDrawingReleaseWorkflowTests(APITestCase):
    def setUp(self):
        self.office_user = User.objects.create_user(
            username='office-user',
            password='test-pass',
        )
        self.office_user.is_superuser = True
        self.office_user.save(update_fields=['is_superuser'])
        self.client.force_authenticate(self.office_user)

        self.customer = Customer.objects.create(
            code='CUST-1',
            name='Test Customer',
        )
        self.job_order = JobOrder.objects.create(
            job_no='JOB-1',
            title='Test Job',
            customer=self.customer,
            status='on_hold',
        )

    def test_release_patch_cannot_bypass_peer_review_status(self):
        release = TechnicalDrawingRelease.objects.create(
            job_order=self.job_order,
            revision_number=1,
            folder_path='//server/drawings/JOB-1',
            changelog='Initial release',
            status='pending_approval',
            released_by=self.office_user,
        )

        response = self.client.patch(
            f'/projects/drawing-releases/{release.id}/',
            {'status': 'released'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        release.refresh_from_db()
        self.assertEqual(release.status, 'pending_approval')

    def test_job_resume_is_blocked_while_revision_release_awaits_approval(self):
        old_release = TechnicalDrawingRelease.objects.create(
            job_order=self.job_order,
            revision_number=1,
            folder_path='//server/drawings/JOB-1/rev1',
            changelog='Initial release',
            status='in_revision',
            released_by=self.office_user,
        )
        TechnicalDrawingRelease.objects.create(
            job_order=self.job_order,
            revision_number=2,
            folder_path='//server/drawings/JOB-1/rev2',
            changelog='Revision complete',
            status='pending_approval',
            released_by=self.office_user,
            supersedes=old_release,
        )

        response = self.client.post(
            f'/projects/job-orders/{self.job_order.job_no}/resume/',
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.job_order.refresh_from_db()
        self.assertEqual(self.job_order.status, 'on_hold')
