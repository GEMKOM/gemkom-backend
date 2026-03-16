from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm


class IsWeldingUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_welding')


def can_view_all_money(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_header_totals_only(user) -> bool:
    return user_has_role_perm(user, 'view_all_user_hours') and not can_view_all_money(user)


def can_view_all_users_hours(user) -> bool:
    return user_has_role_perm(user, 'view_all_user_hours')
