from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm


class CanMarkDelivered(BasePermission):
    """Allow superusers and users with the mark_delivered permission."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'mark_delivered')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
