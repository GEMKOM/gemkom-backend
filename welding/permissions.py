from rest_framework.permissions import BasePermission


class IsWeldingUserOrAdmin(BasePermission):
    """
    Permission class for welding operations.
    Allows access to:
    - Superusers
    - Admin users (office location)
    - Users in the 'welding' team
    """
    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)

        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
                or getattr(profile, "team", "").lower() == "welding"
                or getattr(profile, "work_location", "").lower() == "office"
            )
        )
