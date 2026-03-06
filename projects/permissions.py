from rest_framework import permissions
from rest_framework.permissions import BasePermission


# ---------------------------------------------------------------------------
# Cost visibility
# ---------------------------------------------------------------------------

def _is_cost_authorized(user) -> bool:
    """
    Full cost access: management team members, OR planning team managers.
    """
    prof = getattr(user, 'profile', None)
    if not prof:
        return False
    if prof.team == 'management':
        return True
    if prof.team == 'planning' and prof.occupation == 'manager':
        return True
    return False


class IsCostAuthorized(BasePermission):
    """
    Full cost visibility (cost table, cost summary, margins).
    Allowed: superusers, management team, planning team managers.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        return _is_cost_authorized(u)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsProcurementCostAuthorized(BasePermission):
    """
    Material / procurement cost lines.
    Allowed: IsCostAuthorized + procurement team + all planning team members.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        prof = getattr(u, 'profile', None)
        if prof and prof.team in {'procurement', 'planning'}:
            return True
        return _is_cost_authorized(u)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsQCCostAuthorized(BasePermission):
    """
    QC cost lines.
    Allowed: IsCostAuthorized + quality control team.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        prof = getattr(u, 'profile', None)
        if prof and prof.team == 'qualitycontrol':
            return True
        return _is_cost_authorized(u)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsShippingCostAuthorized(BasePermission):
    """
    Shipping cost lines.
    Allowed: IsCostAuthorized + logistics team.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        prof = getattr(u, 'profile', None)
        if prof and prof.team == 'logistics':
            return True
        return _is_cost_authorized(u)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsPlanning(BasePermission):
    """
    Any planning team member.
    Used to gate actions like marking a job order cost as not applicable.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        prof = getattr(u, 'profile', None)
        return bool(prof and prof.team == 'planning')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


# ---------------------------------------------------------------------------
# Legacy / general
# ---------------------------------------------------------------------------

class IsOfficeUser(permissions.BasePermission):
    """Only users with work_location='office' can access."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Check if user has UserProfile with office location
        try:
            return request.user.userprofile.work_location == 'office'
        except AttributeError:
            # Fallback to is_admin
            return getattr(request.user, 'is_admin', False)


class IsTopicOwnerOrReadOnly(permissions.BasePermission):
    """Only topic owner can edit/delete."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.created_by == request.user


class IsCommentAuthorOrReadOnly(permissions.BasePermission):
    """Only comment author can edit/delete."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.created_by == request.user
