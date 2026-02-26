from rest_framework.permissions import BasePermission


class IsSalesUser(BasePermission):
    """Allow sales team members and managers/superusers."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        prof = getattr(request.user, 'profile', None)
        return bool(prof and prof.team in ('sales', 'management'))
