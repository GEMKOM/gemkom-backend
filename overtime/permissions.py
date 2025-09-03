# overtime/permissions.py
from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsRequesterOrAdmin(BasePermission):
    """
    - Requester can read & update their own.
    - Users included as entry line can read.
    - Admins (superuser or user.profile.location_type == "office") can do anything.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_admin:
            return True

        if request.method in SAFE_METHODS:
            # view allowed for requester or anyone included in entries
            if obj.requester_id == user.id:
                return True
            return obj.entries.filter(user=user).exists()

        # modifying:
        return obj.requester_id == user.id
