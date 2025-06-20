

from users.permissions import IsAdmin, IsMachiningUser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied

class MachiningProtectedView(APIView):
    def dispatch(self, request, *args, **kwargs):
        # Ensure user is authenticated first
        if not request.user or not request.user.is_authenticated:
            raise PermissionDenied("Authentication required.")

        # Check if either permission grants access
        if not (IsAdmin().has_permission(request, self) or IsMachiningUser().has_permission(request, self)):
            raise PermissionDenied("Not authorized for machining operations.")

        return super().dispatch(request, *args, **kwargs)