from django.contrib.auth.models import User
from django.test import TestCase

from users.serializers import UserListSerializer


class UserListSerializerTests(TestCase):
    def test_serializer_does_not_expose_national_id(self):
        user = User.objects.create_user(username="employee")
        user.profile.tc_kimlik_no = "12345678901"
        user.profile.save(update_fields=["tc_kimlik_no"])

        data = UserListSerializer(user).data

        self.assertNotIn("tc_kimlik_no", data)
