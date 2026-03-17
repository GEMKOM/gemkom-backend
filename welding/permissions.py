from rest_framework.permissions import BasePermission
from users.permissions import (
    user_has_role_perm,
    can_view_all_money,
    can_view_all_users_hours,
    can_view_header_totals_only,
)


class IsWeldingUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_welding')
