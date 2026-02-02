from rest_framework import permissions


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
