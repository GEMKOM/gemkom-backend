from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView
from users.permissions import IsAdmin, IsMachiningUser  # your custom permissions

class MachiningProtectedView(APIView):
    authentication_classes = [JWTAuthentication]  # Ensure JWT auth is applied

    def dispatch(self, request, *args, **kwargs):
        # Run authentication manually
        for authenticator in self.authentication_classes:
            auth_result = authenticator().authenticate(request)
            if auth_result is not None:
                request.user, request.auth = auth_result
                break

        # Ensure the user is authenticated
        if not request.user or not request.user.is_authenticated:
            raise PermissionDenied("Authentication required.")

        # Check custom permissions
        if not (IsAdmin().has_permission(request, self) or IsMachiningUser().has_permission(request, self)):
            raise PermissionDenied("Not authorized for machining operations.")

        return super().dispatch(request, *args, **kwargs)