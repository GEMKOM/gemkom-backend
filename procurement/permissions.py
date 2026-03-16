from rest_framework.permissions import BasePermission
from users.permissions import user_has_role_perm


class IsFinanceAuthorized(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_finance')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class IsFinanceOrPlanningAuthorized(BasePermission):
    """Finance teams AND planning team (e.g. for ItemViewSet)."""

    def has_permission(self, request, view):
        u = request.user
        return user_has_role_perm(u, 'access_finance') or user_has_role_perm(u, 'access_planning_write')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)