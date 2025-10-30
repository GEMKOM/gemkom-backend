from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsMachiningUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)

        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
                or getattr(profile, "team", "").lower() == "machining"
                or getattr(profile, "work_location", "").lower() == "office"
            )
        )
    
class IsCuttingUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)

        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
                or getattr(profile, "team", "").lower() == "cutting"
                or getattr(profile, "work_location", "").lower() == "office"
            )
        )

class IsOfficeUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)

        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
                or getattr(profile, "work_location", "").lower() == "office"
            )
        )

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (
                user.is_superuser
                or user.is_admin
            )
        )
    

HR_GROUPS = {"HR", "Management"}
HR_TEAMS  = {"human_resouces", "management"}  # note: your enum uses 'human_resouces'

def _required_perm_for(method: str) -> str:
    """
    Map HTTP method -> Django model permission codename for users.WageRate.
    """
    app_label = "users"
    model_codename = "wagerate"  # Django builds perms as <app_label>.<action>_<modelnamelower>
    if method in SAFE_METHODS:          # GET, HEAD, OPTIONS
        action = "view"
    elif method == "POST":
        action = "add"
    elif method in ("PUT", "PATCH"):
        action = "change"
    elif method == "DELETE":
        action = "delete"
    else:
        # default to view for unknown/rare methods
        action = "view"
    return f"{app_label}.{action}_{model_codename}"

def _is_hr_or_management(user) -> bool:
    # Group-based check
    if user.groups.filter(name__in=HR_GROUPS).exists():
        return True
    # Profile team check (only if present)
    prof = getattr(user, "profile", None)
    if prof and prof.team in HR_TEAMS:
        return True
    return False

class IsHRorAuthorized(BasePermission):
    """
    Allow superusers.
    Otherwise require BOTH:
      (A) user has the specific model permission for the action, AND
      (B) user is HR/Management (group OR profile.team).
    """

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, "is_superuser", False):
            return True

        required = _required_perm_for(request.method)
        has_perm = u.has_perm(required)
        in_hr = _is_hr_or_management(u)

        return bool(has_perm and in_hr)

    def has_object_permission(self, request, view, obj):
        # Mirror the same logic at object-level (in case you later restrict per-object)
        return self.has_permission(request, view)