from rest_framework.permissions import BasePermission, SAFE_METHODS

FINANCE_TEAMS  = {"finance", "procurement", "management"}  # note: your enum uses 'human_resouces'


def _is_finance_authorized(user) -> bool:
    # Profile team check (only if present)
    prof = getattr(user, "profile", None)
    if prof and prof.team in FINANCE_TEAMS:
        return True
    return False

class IsFinanceAuthorized(BasePermission):

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if getattr(u, "is_superuser", False):
            return True

        is_authorized = _is_finance_authorized(u)

        return bool(is_authorized)

    def has_object_permission(self, request, view, obj):
        # Mirror the same logic at object-level (in case you later restrict per-object)
        return self.has_permission(request, view)