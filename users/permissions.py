from rest_framework.permissions import BasePermission

class IsMachiningUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)

        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
                or getattr(profile, "team", "").lower() == "machining"
            )
        )

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
            )
        )