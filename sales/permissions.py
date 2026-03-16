from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm


class IsSalesUser(BasePermission):
    """Allow sales team members and managers/superusers."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_sales')
