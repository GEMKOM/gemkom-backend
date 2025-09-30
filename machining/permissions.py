from rest_framework.views import APIView
from users.permissions import IsMachiningUserOrAdmin  # your custom permissions
from rest_framework.permissions import IsAuthenticated

from rest_framework.permissions import BasePermission
from django.conf import settings

class HasQueueSecret(BasePermission):
    def has_permission(self, request, view):
        return settings.QUEUE_SECRET and request.headers.get("X-Queue-Secret") == settings.QUEUE_SECRET

class MachiningProtectedView(APIView):
    permission_classes = [IsAuthenticated, IsMachiningUserOrAdmin]