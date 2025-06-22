from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.views import APIView
from users.permissions import IsMachiningUserOrAdmin  # your custom permissions
from rest_framework.permissions import IsAuthenticated

class MachiningProtectedView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsMachiningUserOrAdmin]