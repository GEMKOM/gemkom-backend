from __future__ import annotations

from django.contrib.auth.models import User, Permission


def sync_user_permissions(user: User, position) -> None:
    """
    Set user.user_permissions to match their Position's permission set.
    Called whenever UserProfile.position changes (via signal).

    UserPermissionOverride entries (explicit grant/deny) are stored on
    user.permission_overrides — those are checked first in user_has_role_perm()
    and are unaffected by this function.
    """
    if position is None:
        user.user_permissions.clear()
    else:
        codenames = list(position.permissions.values_list('codename', flat=True))
        perms = Permission.objects.filter(
            codename__in=codenames,
            content_type__app_label='users',
        )
        user.user_permissions.set(perms)

    # Clear Django's internal permission cache so has_perm() reflects the change
    for attr in ('_perm_cache', '_user_perm_cache', '_user_obj_perm_cache'):
        user.__dict__.pop(attr, None)


def resolve_chain_approvers(position, climb: int) -> list[int]:
    """
    Find the Nth non-vacant, active ancestor of `position`, where N = `climb`.

    Walks up the tree counting only non-vacant active positions. Vacant or
    inactive positions are skipped without consuming a step. Returns the holders
    of exactly the Nth ancestor — not everyone along the way.

    This means climb_levels=1 → direct manager, climb_levels=2 → manager's
    manager. Using these on separate stages ensures each person sees the request
    exactly once.

    Returns a deduplicated list of user IDs, or [] if the chain is too short.
    """
    from users.models import UserProfile

    steps_taken = 0
    pos = position

    while pos.parent_id:
        pos = pos.parent
        if not pos.is_active:
            continue
        holder_ids = list(
            UserProfile.objects.filter(
                position=pos,
                user__is_active=True,
            ).values_list('user_id', flat=True)
        )
        if not holder_ids:
            continue
        steps_taken += 1
        if steps_taken == climb:
            return list(dict.fromkeys(holder_ids))

    return []


def is_org_supervisor(supervisor_user, subordinate_user) -> bool:
    """
    True if supervisor_user holds an active position that is an ancestor of
    subordinate_user's position in the org tree (any number of levels up).

    Users without a position, peers (same position), and the user themself
    all return False.
    """
    if not supervisor_user or not subordinate_user:
        return False
    if supervisor_user.pk == subordinate_user.pk:
        return False

    sup_pos = _position_of(supervisor_user)
    sub_pos = _position_of(subordinate_user)
    if sup_pos is None or sub_pos is None or not sup_pos.is_active:
        return False

    seen = set()
    pos = sub_pos
    while pos.parent_id and pos.parent_id not in seen:
        if pos.parent_id == sup_pos.pk:
            return True
        seen.add(pos.parent_id)
        pos = pos.parent
    return False


def _position_of(user):
    profile = getattr(user, 'profile', None)
    return profile.position if profile else None


def get_dept_members(dept_code: str):
    """
    Return a queryset of active users whose position has the given department_code tag.
    """
    if not dept_code:
        return User.objects.none()
    return User.objects.filter(
        is_active=True,
        profile__position__department_code=dept_code,
        profile__position__is_active=True,
    ).distinct()
