from rest_framework.permissions import BasePermission, SAFE_METHODS


# ---------------------------------------------------------------------------
# Central permission resolver
# ---------------------------------------------------------------------------

def user_has_role_perm(user, codename: str) -> bool:
    """
    Check whether *user* has the given custom permission codename.

    Resolution order:
      1. Superuser → True
      2. Explicit deny UserPermissionOverride → False
      3. Explicit grant UserPermissionOverride → True
      4. Django group/permission system (user.has_perm) → result
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True

    try:
        override = user.permission_overrides.filter(codename=codename).only('granted').first()
        if override is not None:
            return override.granted
    except Exception:
        pass

    return user.has_perm(f'users.{codename}')


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return u and u.is_authenticated and (u.is_superuser or u.is_staff)


class IsOfficeUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'office_access')


# ---------------------------------------------------------------------------
# HR / wage rate permissions
# ---------------------------------------------------------------------------

def _required_perm_for(method: str) -> str:
    app_label = 'users'
    model_codename = 'wagerate'
    if method in SAFE_METHODS:
        action = 'view'
    elif method == 'POST':
        action = 'add'
    elif method in ('PUT', 'PATCH'):
        action = 'change'
    elif method == 'DELETE':
        action = 'delete'
    else:
        action = 'view'
    return f'{app_label}.{action}_{model_codename}'


class IsHRorAuthorized(BasePermission):
    """
    Allow superusers.
    Otherwise require BOTH:
      (A) user has the specific model permission for the action, AND
      (B) user has the manage_hr role permission.
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, 'is_superuser', False):
            return True
        return u.has_perm(_required_perm_for(request.method)) and user_has_role_perm(u, 'manage_hr')

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


# ---------------------------------------------------------------------------
# Cost visibility helpers
# ---------------------------------------------------------------------------

def can_see_job_costs(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_all_money(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_all_users_hours(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_header_totals_only(user) -> bool:
    return False
