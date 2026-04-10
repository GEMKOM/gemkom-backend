from rest_framework.permissions import BasePermission

from users.permissions import user_has_role_perm


class IsHROrAdmin(BasePermission):
    """
    Grants access to HR staff and superusers/staff.
    HR is identified by the 'manage_hr' role permission (same codename used by WageRate).
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser or u.is_staff:
            return True
        return user_has_role_perm(u, 'manage_hr')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
