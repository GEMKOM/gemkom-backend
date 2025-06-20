from rest_framework.permissions import BasePermission

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user and user.is_authenticated and (
                user.is_superuser or
                getattr(user, 'is_admin', False)
            )
        )

class IsMachiningUser(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user and user.is_authenticated and (
                getattr(user, 'team', '').lower() == 'machining'
            )
        )