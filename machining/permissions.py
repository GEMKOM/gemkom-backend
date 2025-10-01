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

# ---- permission helpers ----
def _team_of(user) -> str | None:
    try:
        return (user.profile.team or "").lower()
    except Exception:
        return None

def can_view_all_money(user) -> bool:
    # managers and superusers see everything
    team = _team_of(user)
    return bool(
        user.is_superuser
        or team == "management"    # in case you use this label
    )

def can_view_header_totals_only(user) -> bool:
    # manufacturing & planning see header total(s) but not per-user money
    team = _team_of(user)
    return team in {"manufacturing", "planning"}

def can_view_all_users_hours(user) -> bool:
    # manufacturing & planning can see everyone's hours
    return can_view_all_money(user) or can_view_header_totals_only(user)