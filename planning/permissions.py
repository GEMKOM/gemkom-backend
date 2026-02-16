from rest_framework.permissions import BasePermission

DELIVERY_TEAMS = {"procurement", "planning", "warehouse"}


class CanMarkDelivered(BasePermission):
    """Allow superusers and users in procurement, planning, or warehouse teams."""

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, "is_superuser", False):
            return True
        prof = getattr(u, "profile", None)
        return bool(prof and prof.team in DELIVERY_TEAMS)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
