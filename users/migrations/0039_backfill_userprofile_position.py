"""
Data migration: assign each UserProfile a Position based on their current
Django group membership and occupation field.

Strategy:
  1. For each active user with group membership, determine their department
     via GROUP_TO_DEPT mapping.
  2. Determine their level from occupation:
       'manager' → level 4 (manager/chief)
       anything else → level 5 or 6 (staff)
  3. Find the best matching Position: same department, best level match,
     is_active=True.
  4. Assign profile.position and call sync_user_permissions to set
     user.user_permissions from the position.

Users with no groups (or only admin groups) are left with position=None.
"""
from django.db import migrations


# Same mapping as users/helpers.py GROUP_TO_DEPT — inlined to avoid live-code import
GROUP_TO_DEPT = {
    'machining_team':          'machining',
    'design_team':             'design',
    'logistics_team':          'logistics',
    'procurement_team':        'procurement',
    'welding_team':            'welding',
    'planning_team':           'planning',
    'planning_manager':        'planning',
    'manufacturing_team':      'manufacturing',
    'maintenance_team':        'maintenance',
    'qualitycontrol_team':     'qualitycontrol',
    'cutting_team':            'cutting',
    'warehouse_team':          'warehouse',
    'finance_team':            'finance',
    'accounting_team':         'accounting',
    'management_team':         'management',
    'hr_team':                 'human_resources',
    'sales_team':              'sales',
    'external_workshops_team': 'external_workshops',
}

MANAGER_GROUPS = {
    'planning_manager',
    'management_team',
}


def _get_dept_code(user_groups_names: list[str]) -> str | None:
    for name in user_groups_names:
        if name in GROUP_TO_DEPT:
            return GROUP_TO_DEPT[name]
    return None


def _is_manager(user_groups_names: list[str], occupation: str) -> bool:
    if occupation == 'manager':
        return True
    if any(g in MANAGER_GROUPS for g in user_groups_names):
        return True
    return False


def backfill_positions(apps, schema_editor):
    UserProfile = apps.get_model('users', 'UserProfile')
    try:
        Position = apps.get_model('organization', 'Position')
        Department = apps.get_model('organization', 'Department')
    except LookupError:
        # These models were dropped from the organization app by later
        # migrations. On a fresh database the migration plan reaches this
        # point with the post-removal state — and with no users to backfill,
        # skipping is equivalent to what production already ran.
        return
    Permission = apps.get_model('auth', 'Permission')
    PermissionMeta = apps.get_model('users', 'PermissionMeta')

    dept_cache = {}
    position_cache = {}  # dept_code → {level: Position}

    def get_dept(code):
        if code not in dept_cache:
            dept_cache[code] = Department.objects.filter(code=code).first()
        return dept_cache[code]

    def get_position(dept_code, preferred_level):
        key = (dept_code, preferred_level)
        if key not in position_cache:
            dept = get_dept(dept_code)
            if not dept:
                position_cache[key] = None
                return None
            # Try exact level first, then walk levels upward/downward
            pos = None
            for lvl in [preferred_level, preferred_level + 1, preferred_level - 1, 5, 6, 4]:
                pos = Position.objects.filter(
                    department=dept, level=lvl, is_active=True
                ).first()
                if pos:
                    break
            position_cache[key] = pos
        return position_cache[key]

    for profile in UserProfile.objects.select_related('user').prefetch_related(
        'user__groups'
    ).filter(user__is_active=True):
        user = profile.user
        group_names = list(user.groups.values_list('name', flat=True))
        dept_code = _get_dept_code(group_names)
        if not dept_code:
            continue

        is_mgr = _is_manager(group_names, getattr(profile, 'occupation', '') or '')
        preferred_level = 4 if is_mgr else 5

        position = get_position(dept_code, preferred_level)
        if not position:
            continue

        profile.position = position
        profile.save(update_fields=['position'])

        # Sync permissions — replicate what sync_user_permissions does
        # (can't call it directly as we're using apps registry objects)
        codenames = list(position.permissions.values_list('codename', flat=True))
        perms = Permission.objects.filter(
            codename__in=codenames,
            content_type__app_label='users',
        )
        user.user_permissions.set(perms)


def reverse_backfill(apps, schema_editor):
    UserProfile = apps.get_model('users', 'UserProfile')
    UserProfile.objects.filter(position__isnull=False).update(position=None)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0038_userprofile_position_fk'),
        ('organization', '0003_seed_positions_and_permissions'),
    ]

    operations = [
        migrations.RunPython(backfill_positions, reverse_backfill),
    ]
