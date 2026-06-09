from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Customer,
    JobOrder,
    JobOrderDepartmentTask,
    JobOrderDiscussionTopic,
    TechnicalDrawingRelease,
)


class TechnicalDrawingReleaseWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='designer',
            email='designer@example.com',
            password='password',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.customer = Customer.objects.create(code='CUST', name='Customer')

    def test_complete_revision_rolls_back_when_design_task_cannot_complete(self):
        job_order = JobOrder.objects.create(
            job_no='JO-001',
            title='Revision job',
            customer=self.customer,
            status='on_hold',
        )
        design_task = JobOrderDepartmentTask.objects.create(
            job_order=job_order,
            department='design',
            title='Design',
            status='in_progress',
        )
        design_subtask = JobOrderDepartmentTask.objects.create(
            job_order=job_order,
            department='design',
            title='Incomplete design subtask',
            status='pending',
            parent=design_task,
        )
        manufacturing_task = JobOrderDepartmentTask.objects.create(
            job_order=job_order,
            department='manufacturing',
            title='Manufacturing',
            status='on_hold',
        )
        release = TechnicalDrawingRelease.objects.create(
            job_order=job_order,
            revision_number=1,
            folder_path='//server/releases/JO-001/R1',
            changelog='Initial release',
            status='in_revision',
            released_by=self.user,
        )
        revision_topic = JobOrderDiscussionTopic.objects.create(
            job_order=job_order,
            title='Revision request',
            content='Please revise',
            topic_type='revision_request',
            revision_status='in_progress',
            related_release=release,
            created_by=self.user,
        )

        response = self.client.post(
            f'/projects/drawing-releases/{release.id}/complete_revision/',
            {
                'folder_path': '//server/releases/JO-001/R2',
                'changelog': 'Revision complete',
                'revision_code': 'R2',
                'hardcopy_count': 0,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        job_order.refresh_from_db()
        release.refresh_from_db()
        revision_topic.refresh_from_db()
        design_task.refresh_from_db()
        design_subtask.refresh_from_db()
        manufacturing_task.refresh_from_db()

        self.assertEqual(job_order.status, 'on_hold')
        self.assertEqual(release.status, 'in_revision')
        self.assertEqual(revision_topic.revision_status, 'in_progress')
        self.assertEqual(design_task.status, 'in_progress')
        self.assertEqual(design_subtask.status, 'pending')
        self.assertEqual(manufacturing_task.status, 'on_hold')
        self.assertEqual(TechnicalDrawingRelease.objects.filter(job_order=job_order).count(), 1)
        self.assertFalse(
            JobOrderDiscussionTopic.objects.filter(
                job_order=job_order,
                topic_type='drawing_release',
                title__contains='R2',
            ).exists()
        )
