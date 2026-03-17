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
      5. Legacy team/occupation fallback (safety net during transition) → result
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True

    # Overrides (Phase 6 model — safe to query even before the table exists)
    try:
        override = user.permission_overrides.filter(codename=codename).only('granted').first()
        if override is not None:
            return override.granted
    except Exception:
        pass

    # Django permission system (per-request cached after first has_perm call)
    if user.has_perm(f'users.{codename}'):
        return True

    # Legacy fallback — keeps existing behaviour for users not yet in any group
    return _legacy_team_check(user, codename)


def _legacy_team_check(user, codename: str) -> bool:
    """
    Mirrors the original team/occupation checks.
    Remove this function (and the fallback call above) once all users have
    been assigned to Django Groups.
    """
    prof = getattr(user, 'profile', None)
    team = (getattr(prof, 'team', '') or '').lower()
    occ  = (getattr(prof, 'occupation', '') or '').lower()

    LEGACY: dict[str, bool] = {
        'access_machining':          team == 'machining',
        'access_cutting':            team == 'cutting',
        'access_welding':            team == 'welding',
        'access_sales':              team in ('sales', 'management'),
        'access_finance':            team in ('finance', 'procurement', 'management', 'external_workshops'),
        'access_planning_write':     team == 'planning',
        'access_warehouse_write':    team == 'warehouse',
        'access_procurement_write':  team == 'procurement',
        'mark_delivered':            team in ('procurement', 'planning', 'warehouse'),
        'manage_hr':                 team in ('human_resouces', 'management'),
        'view_job_costs':            team == 'management' or (team == 'planning' and occ == 'manager') or team == 'sales',
        'view_all_user_hours':       team in ('manufacturing', 'planning', 'management'),
        'view_procurement_costs':    team in ('procurement', 'planning', 'management'),
        'view_qc_costs':             team in ('qualitycontrol', 'management'),
        'view_shipping_costs':       team in ('logistics', 'management'),
        'manage_planning_requests':  team == 'planning',
        'view_finance_pages':        team in ('finance', 'procurement', 'management', 'external_workshops'),
        'view_hr_pages':             team in ('human_resouces', 'management'),
        'view_cost_pages':           team == 'management' or (team == 'planning' and occ == 'manager') or team == 'sales',
    }
    return LEGACY.get(codename, False)


# ---------------------------------------------------------------------------
# Permission classes
# ---------------------------------------------------------------------------

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (user.is_superuser or user.is_staff)
        )


class IsMachiningUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_machining')


class IsCuttingUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_cutting')


class IsOfficeUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'office_access')


# ---------------------------------------------------------------------------
# HR / wage rate permissions
# ---------------------------------------------------------------------------

def _required_perm_for(method: str) -> str:
    """Map HTTP method → Django model permission codename for users.WageRate."""
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
# Legacy helper kept for backward compatibility (used by other modules)
# ---------------------------------------------------------------------------

def can_see_job_costs(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


# ---------------------------------------------------------------------------
# Shared cost/hours visibility helpers (used by machining, welding, etc.)
# ---------------------------------------------------------------------------

def can_view_all_money(user) -> bool:
    return user_has_role_perm(user, 'view_job_costs')


def can_view_all_users_hours(user) -> bool:
    return user_has_role_perm(user, 'view_all_user_hours')


def can_view_header_totals_only(user) -> bool:
    return can_view_all_users_hours(user) and not can_view_all_money(user)