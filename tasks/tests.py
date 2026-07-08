from django.test import SimpleTestCase

from .serializers import PartListSerializer, PartSerializer


class PartSerializerPermissionTests(SimpleTestCase):
    def test_department_request_is_server_managed(self):
        self.assertIn('department_request', PartSerializer.Meta.read_only_fields)
        self.assertIn('department_request', PartListSerializer.Meta.read_only_fields)
