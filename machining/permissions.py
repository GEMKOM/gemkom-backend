from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, BasePermission
from django.conf import settings
from users.permissions import (
    IsMachiningUserOrAdmin,
    can_view_all_money,
    can_view_all_users_hours,
    can_view_header_totals_only,
)


class HasQueueSecret(BasePermission):
    def has_permission(self, request, view):
        return settings.QUEUE_SECRET and request.headers.get("X-Queue-Secret") == settings.QUEUE_SECRET


class MachiningProtectedView(APIView):
    permission_classes = [IsAuthenticated, IsMachiningUserOrAdmin]