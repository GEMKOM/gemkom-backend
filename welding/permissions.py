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


# ---- permission helpers ----
def _team_of(user) -> str | None:
    try:
        return (user.profile.team or "").lower()
    except Exception:
        return None


def can_view_all_money(user) -> bool:
    """
    Managers and superusers see everything (hours + costs).
    """
    team = _team_of(user)
    return bool(
        user.is_superuser
        or team == "management"
    )


def can_view_header_totals_only(user) -> bool:
    """
    Manufacturing & planning see header totals but not per-user money.
    """
    team = _team_of(user)
    return team in {"manufacturing", "planning"}


def can_view_all_users_hours(user) -> bool:
    """
    Manufacturing & planning can see everyone's hours.
    """
    return can_view_all_money(user) or can_view_header_totals_only(user)
