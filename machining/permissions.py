from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, BasePermission
from django.conf import settings
from users.permissions import IsMachiningUserOrAdmin, user_has_role_perm


class HasQueueSecret(BasePermission):
    def has_permission(self, request, view):
        return settings.QUEUE_SECRET and request.headers.get("X-Queue-Secret") == settings.QUEUE_SECRET


class MachiningProtectedView(APIView):
    permission_classes = [IsAuthenticated, IsMachiningUserOrAdmin]


def can_view_all_money(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_header_totals_only(user) -> bool:
    return user_has_role_perm(user, 'view_all_user_hours') and not can_view_all_money(user)


def can_view_all_users_hours(user) -> bool:
    return user_has_role_perm(user, 'view_all_user_hours')