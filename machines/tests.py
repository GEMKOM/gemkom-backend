from django.contrib.auth.models import AnonymousUser, User
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from users.permissions import IsAdmin

from .views import MachineDetailView, MachineListCreateView


class MachinePermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.regular_user = User(username="regular", is_staff=False)
        self.admin_user = User(username="admin", is_staff=True)

    def _allowed(self, view, request):
        view.request = request
        return all(permission.has_permission(request, view) for permission in view.get_permissions())

    def test_machine_create_requires_admin(self):
        view = MachineListCreateView()

        regular_request = self.factory.post("/machines/", {})
        regular_request.user = self.regular_user
        self.assertFalse(self._allowed(view, regular_request))

        admin_request = self.factory.post("/machines/", {})
        admin_request.user = self.admin_user
        self.assertTrue(self._allowed(view, admin_request))

    def test_machine_detail_mutations_require_admin(self):
        for method in ("put", "patch", "delete"):
            request = getattr(self.factory, method)("/machines/1/", {})
            request.user = self.regular_user
            view = MachineDetailView()

            self.assertFalse(self._allowed(view, request))
            self.assertTrue(any(isinstance(permission, IsAdmin) for permission in view.get_permissions()))

    def test_machine_detail_read_requires_authentication_only(self):
        view = MachineDetailView()

        anonymous_request = self.factory.get("/machines/1/")
        anonymous_request.user = AnonymousUser()
        self.assertFalse(self._allowed(view, anonymous_request))

        regular_request = self.factory.get("/machines/1/")
        regular_request.user = self.regular_user
        self.assertTrue(self._allowed(view, regular_request))
