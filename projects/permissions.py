from rest_framework import permissions
from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm, IsOfficeUserOrAdmin


class IsCostAuthorized(BasePermission):
    """Full cost visibility (cost table, cost summary, margins)."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_job_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsProcurementCostAuthorized(BasePermission):
    """Material / procurement cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_job_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsQCCostAuthorized(BasePermission):
    """QC cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_job_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsShippingCostAuthorized(BasePermission):
    """Shipping cost lines."""

    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'view_job_costs')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsPlanning(BasePermission):
    """Authenticated users — planning access now open."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsOfficeUser(IsOfficeUserOrAdmin):
    """Office portal users. Delegates to office_access permission."""


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
