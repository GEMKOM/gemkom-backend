from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from quality_control.models import NCR
from .models import (
    Customer,
    JobOrder,
    JobOrderDepartmentTask,
    JobOrderDiscussionTopic,
    TechnicalDrawingRelease,
)
from .views import TechnicalDrawingReleaseViewSet


class TechnicalDrawingReleaseNCRGateTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_superuser(
            username='office',
            email='office@example.com',
            password='password',
        )
        self.customer = Customer.objects.create(
            code='CUST',
            name='Customer',
        )

    def _create_job_with_open_ncr(self, job_no='JOB-001', status_value='active'):
        job_order = JobOrder.objects.create(
            job_no=job_no,
            title='Job order',
            customer=self.customer,
            status=status_value,
        )
        design_task = JobOrderDepartmentTask.objects.create(
            job_order=job_order,
            department='design',
            title='Design',
            status='in_progress',
        )
        NCR.objects.create(
            job_order=job_order,
            title='Open NCR',
            description='Blocks task completion',
            detected_by=self.user,
            created_by=self.user,
            status='draft',
        )
        return job_order, design_task

    def test_create_rolls_back_release_when_ncr_blocks_auto_complete(self):
        job_order, design_task = self._create_job_with_open_ncr()
        view = TechnicalDrawingReleaseViewSet.as_view({'post': 'create'})
        request = self.factory.post(
            '/projects/drawing-releases/',
            {
                'job_order': job_order.pk,
                'folder_path': r'\\server\drawings\JOB-001',
                'changelog': 'Initial release',
                'auto_complete_design_task': True,
            },
            format='json',
        )
        force_authenticate(request, user=self.user)

        response = view(request)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('NCR', response.data['message'])
        self.assertFalse(TechnicalDrawingRelease.objects.filter(job_order=job_order).exists())
        self.assertFalse(JobOrderDiscussionTopic.objects.filter(job_order=job_order).exists())
        design_task.refresh_from_db()
        self.assertEqual(design_task.status, 'in_progress')

    def test_complete_revision_rolls_back_release_updates_when_ncr_blocks_design_task(self):
        job_order, design_task = self._create_job_with_open_ncr(
            job_no='JOB-002',
            status_value='on_hold',
        )
        release = TechnicalDrawingRelease.objects.create(
            job_order=job_order,
            revision_number=1,
            folder_path=r'\\server\drawings\JOB-002',
            changelog='Original release',
            status='in_revision',
            released_by=self.user,
        )
        revision_topic = JobOrderDiscussionTopic.objects.create(
            job_order=job_order,
            title='Revision request',
            content='Please revise',
            priority='high',
            topic_type='revision_request',
            revision_status='in_progress',
            related_release=release,
            created_by=self.user,
        )
        view = TechnicalDrawingReleaseViewSet.as_view({'post': 'complete_revision'})
        request = self.factory.post(
            f'/projects/drawing-releases/{release.pk}/complete_revision/',
            {
                'folder_path': r'\\server\drawings\JOB-002\rev2',
                'changelog': 'Revision complete',
            },
            format='json',
        )
        force_authenticate(request, user=self.user)

        response = view(request, pk=release.pk)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('NCR', response.data['message'])
        release.refresh_from_db()
        revision_topic.refresh_from_db()
        design_task.refresh_from_db()
        job_order.refresh_from_db()
        self.assertEqual(release.status, 'in_revision')
        self.assertEqual(revision_topic.revision_status, 'in_progress')
        self.assertEqual(design_task.status, 'in_progress')
        self.assertEqual(job_order.status, 'on_hold')
        self.assertEqual(TechnicalDrawingRelease.objects.filter(job_order=job_order).count(), 1)
        self.assertFalse(
            JobOrderDiscussionTopic.objects.filter(
                job_order=job_order,
                topic_type='drawing_release',
            ).exists()
        )
