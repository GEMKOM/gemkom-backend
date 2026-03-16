from rest_framework import permissions
from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm


# ---------------------------------------------------------------------------
# Cost visibility
# ---------------------------------------------------------------------------

class IsCostAuthorized(BasePermission):
    """Full cost visibility (cost table, cost summary, margins)."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_job_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsProcurementCostAuthorized(BasePermission):
    """Material / procurement cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_procurement_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsQCCostAuthorized(BasePermission):
    """QC cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_qc_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsShippingCostAuthorized(BasePermission):
    """Shipping cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_shipping_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsPlanning(BasePermission):
    """Any user with planning write access."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_planning_write')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

class IsOfficeUser(permissions.BasePermission):
    """Only staff / superusers can access."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.is_staff or request.user.is_superuser


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
