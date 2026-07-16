from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS  # noqa: F401

from users.permissions import user_has_role_perm


class IsProcurementWrite(BasePermission):
    """
    Read (safe methods): any authenticated user.
    Write: requires the `access_procurement_write` codename.
    """

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user_has_role_perm(u, 'access_procurement_write')
