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


class IsAdminOrStaff(BasePermission):
    """Only Django staff / superusers."""

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_staff or u.is_superuser))


def _in_user_group(user, slug: str) -> bool:
    """True if *user* belongs to the active UserGroup with the given slug."""
    from organization.models import UserGroup
    try:
        group = UserGroup.objects.get(slug=slug, is_active=True)
    except UserGroup.DoesNotExist:
        return False
    return group.get_members().filter(pk=user.pk).exists()


class IsPlanningOrAdmin(BasePermission):
    """
    Django staff / superusers, or members of the 'planlama' UserGroup.

    Mirrors the frontend's canEditJobOrders() gate so users who see the
    action button are actually allowed to perform it.
    """

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if u.is_staff or u.is_superuser:
            return True
        return _in_user_group(u, 'planlama')


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
