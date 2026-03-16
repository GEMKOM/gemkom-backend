# Permissions & RBAC System — Design Plan

## Overview

Use **Django's built-in `Group` and `Permission` models** as the RBAC backbone. No new Role models, no third-party libraries. The existing `profile.team` and `profile.occupation` fields are kept — they remain the source of truth for data, but group membership is managed manually in Django admin going forward.

---

## Why This Approach

- Django Groups already appear in the codebase (`approvals/services.py → resolve_group_user_ids`, `NotificationConfig.users` M2M) — the infrastructure exists
- Django's `user.has_perm()` is per-request cached — one DB query fetches all permissions for a user, subsequent checks are free
- No third-party libraries needed (`django-guardian` is for per-object grants we don't need; `django-role-permissions` adds a layer on top of what Django already provides)
- Backward-compatible: a shim keeps all existing team/occupation checks working during migration

---

## Phase 1 — Register Custom Permission Codenames

Add a `post_migrate` signal in `users/apps.py` that idempotently creates 19 custom `Permission` objects attached to the `UserProfile` ContentType.

| Codename | Description |
|---|---|
| `access_machining` | Can access machining module |
| `access_cutting` | Can access CNC cutting module |
| `access_welding` | Can access welding module |
| `access_sales` | Can access sales module |
| `access_finance` | Can access finance data |
| `access_planning_write` | Can create/edit planning requests |
| `access_warehouse_write` | Can perform warehouse write operations |
| `access_procurement_write` | Can perform procurement write operations |
| `mark_delivered` | Can mark items as delivered |
| `manage_hr` | Can manage HR wage records |
| `view_job_costs` | Can view job cost breakdowns |
| `view_all_user_hours` | Can view all users' hours |
| `view_procurement_costs` | Can view procurement cost lines |
| `view_qc_costs` | Can view QC cost lines |
| `view_shipping_costs` | Can view shipping cost lines |
| `manage_planning_requests` | Can manage planning request lifecycle |
| `view_finance_pages` | Frontend: can see finance pages |
| `view_hr_pages` | Frontend: can see HR pages |
| `view_cost_pages` | Frontend: can see cost breakdown pages |

```python
# users/apps.py
def _create_custom_permissions(sender, **kwargs):
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    from users.models import UserProfile

    ct = ContentType.objects.get_for_model(UserProfile)
    for codename, name in CODENAMES:
        Permission.objects.get_or_create(
            codename=codename, content_type=ct, defaults={'name': name}
        )
```

---

## Phase 2 — Data Migration: Groups + User Assignment

A `RunPython` data migration creates 15 Django Groups with the correct permissions and populates existing users based on their current `team` / `occupation`.

| Group | Permissions |
|---|---|
| `planning_team` | `access_planning_write`, `mark_delivered`, `view_all_user_hours`, `view_procurement_costs`, `manage_planning_requests` |
| `planning_manager` | All of `planning_team` + `view_job_costs`, `view_cost_pages` |
| `procurement_team` | `access_finance`, `access_procurement_write`, `mark_delivered`, `view_finance_pages` |
| `finance_team` | `access_finance`, `view_finance_pages` |
| `accounting_team` | `access_finance`, `view_finance_pages` |
| `management_team` | `access_finance`, `view_job_costs`, `view_all_user_hours`, `view_procurement_costs`, `view_qc_costs`, `view_shipping_costs`, `view_cost_pages`, `view_finance_pages` |
| `machining_team` | `access_machining` |
| `welding_team` | `access_welding` |
| `cutting_team` | `access_cutting` |
| `sales_team` | `access_sales` |
| `warehouse_team` | `access_warehouse_write`, `mark_delivered` |
| `qualitycontrol_team` | `view_qc_costs` |
| `logistics_team` | `view_shipping_costs` |
| `hr_team` | `manage_hr`, `view_hr_pages` |
| `external_workshops_team` | `access_finance`, `view_finance_pages` |

After this migration, group membership is managed manually via Django admin. Changing a user's `team` field no longer auto-updates their groups.

---

## Phase 3 — Compatibility Shim + Rewrite Permission Classes

Add one central function to `users/permissions.py`. All permission classes across all apps delegate to this single function:

```python
def user_has_role_perm(user, codename: str) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    # Primary: Django permission system (cached per-request after first call)
    if user.has_perm(f'users.{codename}'):
        return True
    # Fallback: legacy team check (safety net during transition)
    return _legacy_team_check(user, codename)
```

Every permission class becomes a one-liner:

```python
class IsMachiningUserOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role_perm(request.user, 'access_machining')
```

Files to update:
- `users/permissions.py` — `IsAdmin`, `IsHRorAuthorized`, `IsCostAuthorized`
- `machining/permissions.py` — `IsMachiningUserOrAdmin`
- `cnc_cutting/permissions.py` — cutting check
- `welding/permissions.py` — welding check
- `sales/permissions.py` — `IsSalesUser`
- `procurement/permissions.py` — `IsFinanceAuthorized`
- `planning/permissions.py` + `planning/views.py` — classes + ~15 inline team checks
- `projects/permissions.py` — cost visibility checks

---

## Phase 4 — Frontend Permissions Endpoint

New endpoint: `GET /users/me/permissions/`

Returns a flat `{codename: bool}` dict. One DB query total (Django caches all perms on first `has_perm` call). The frontend fetches this on login and stores it in `localStorage` alongside the user object.

```python
class UserPermissionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.is_superuser:
            return Response({c: True for c in FRONTEND_PERMISSION_CODENAMES})
        return Response({c: user_has_role_perm(user, c) for c in FRONTEND_PERMISSION_CODENAMES})
```

Frontend page visibility: `if permissions.view_finance_pages { show link }`.

> **localStorage note:** The frontend must re-fetch `/users/me/permissions/` whenever user data is refreshed (e.g. after login, after admin changes groups). No backend cache invalidation needed — JWT is stateless.

---

## Phase 5 — Notification Group Routing

Add a `groups` JSONField (default `[]`) to `NotificationConfig`. The routing function in `notifications/service.py` resolves group members:

```python
if cfg.groups:
    group_ids = set(
        User.objects.filter(groups__name__in=cfg.groups, is_active=True)
        .values_list('id', flat=True)
    )
all_ids = explicit_ids | team_ids | group_ids
```

Existing `teams` JSON routing is kept intact. Admins can now route to `planning_manager` instead of hardcoding team + occupation combinations.

---

## Phase 6 — Per-User Permission Overrides

New model for explicit per-user grants or denies that take priority over group membership:

```python
class UserPermissionOverride(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permission_overrides')
    codename   = models.CharField(max_length=100)
    granted    = models.BooleanField(default=True)  # False = explicit deny
    reason     = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'codename')]
```

Resolution order in `user_has_role_perm`:
1. Superuser → `True`
2. Explicit deny override → `False`
3. Explicit grant override → `True`
4. Group permission (`has_perm`) → result
5. Legacy team fallback → result

---

## Phase 7 — Group Mentions in Discussions

Support `@[group:planning_team]` syntax alongside `@username` in discussion comments:

```python
def resolve_mention_users(text: str) -> list[User]:
    users = set()
    for group_name in re.findall(r'@\[group:(\w+)\]', text):
        users.update(Group.objects.get(name=group_name).user_set.filter(is_active=True))
    for username in re.findall(r'@(\w+)', text):
        try:
            users.add(User.objects.get(username=username, is_active=True))
        except User.DoesNotExist:
            pass
    return list(users)
```

Requires the frontend to encode group mentions as `@[group:group_name]`. Reuses existing `TOPIC_MENTION` / `COMMENT_MENTION` notification types.

---

## Migration Risk Summary

| Phase | Risk | Effort | Rollback |
|---|---|---|---|
| 1 — Permission registration | Zero (additive) | 30 min | Delete permissions |
| 2 — Groups + user assignment | Low (additive, no schema change) | 2 hr | Reverse migration clears groups |
| 3 — Shim + rewrite permission classes | Low (fallback guarantees same behavior) | 4–6 hr | Revert files individually |
| 4 — Frontend permissions endpoint | Zero | 1 hr | Remove URL |
| 5 — Notification group routing | Low (additive JSONField) | 1 hr | Remove field |
| 6 — Per-user overrides | Low (new model) | 2 hr | Drop table |
| 7 — Group mentions | Low | 1–2 hr | Remove mention pattern |

Phases 1–3 ship together in one PR. Phases 4–7 are independent and can be merged separately. At any point the system degrades gracefully to the existing team-based checks via the `_legacy_team_check` fallback.

---

## Key Files

| File | Change |
|---|---|
| `users/apps.py` | Add `post_migrate` permission registration |
| `users/permissions.py` | Add `user_has_role_perm()` + `_legacy_team_check()` |
| `users/models.py` | Add `UserPermissionOverride` model |
| `users/views.py` | Add `UserPermissionsView` |
| `users/urls.py` | Register `GET /users/me/permissions/` |
| `users/migrations/` | Data migration: groups + user assignment |
| `machining/permissions.py` | Rewrite to delegate to shim |
| `cnc_cutting/permissions.py` | Rewrite |
| `welding/permissions.py` | Rewrite |
| `sales/permissions.py` | Rewrite |
| `procurement/permissions.py` | Rewrite |
| `planning/permissions.py` + `planning/views.py` | Rewrite classes + inline checks |
| `projects/permissions.py` | Rewrite |
| `notifications/models.py` | Add `groups` JSONField to `NotificationConfig` |
| `notifications/service.py` | Extend `get_route()` to resolve group users |
| `projects/models.py` | Extend mention resolution to support group mentions |
