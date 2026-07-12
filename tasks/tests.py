from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from planning.models import DepartmentRequest
from tasks.models import Part


class ConvertedPartLockTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operator", password="pw")
        self.client.force_authenticate(self.user)
        self.department_request = DepartmentRequest.objects.create(
            title="Converted parts",
            description="",
            department="machining",
            requestor=self.user,
        )
        self.part = Part.objects.create(
            key="PT-LOCK",
            name="Locked part",
            job_no="JOB-1",
            department_request=self.department_request,
        )
        self.url = f"/tasks/parts/{self.part.key}/"

    def test_patch_cannot_clear_department_request_lock(self):
        response = self.client.patch(self.url, {"department_request": None}, format="json")

        self.assertEqual(response.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.department_request_id, self.department_request.id)

    def test_patch_cannot_mutate_converted_part(self):
        response = self.client.patch(self.url, {"name": "Mutated"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.part.refresh_from_db()
        self.assertEqual(self.part.name, "Locked part")

    def test_delete_cannot_remove_converted_part(self):
        response = self.client.delete(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(Part.objects.filter(key=self.part.key).exists())
