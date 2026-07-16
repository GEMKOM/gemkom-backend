from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS  # noqa: F401

from users.permissions import user_has_role_perm


# Procurement is gated by page permissions (see users/migrations/0027).
# There is no standalone "procurement write" codename, so we reuse page
# permissions as write gates:
#   - Rating suppliers  -> the purchase-request-create page permission
#   - Managing suppliers (CRUD + blacklist/status) -> the suppliers-list page perm
RATING_WRITE_PERM = 'access_procurement_purchase_requests_create'
SUPPLIER_WRITE_PERM = 'access_procurement_suppliers_list'


class _WriteGate(BasePermission):
    """Read (safe methods): any authenticated user. Write: requires `write_perm`
    (superuser handled by user_has_role_perm)."""
    write_perm = None

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user_has_role_perm(u, self.write_perm)


class IsProcurementWrite(_WriteGate):
    """Write gate for supplier ratings/evaluations."""
    write_perm = RATING_WRITE_PERM


class IsSupplierWrite(_WriteGate):
    """Write gate for supplier management (CRUD, blacklist/status changes)."""
    write_perm = SUPPLIER_WRITE_PERM
