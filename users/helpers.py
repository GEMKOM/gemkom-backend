# users/helpers.py
from django.contrib.auth.models import User

# ---------------------------------------------------------------------------
# Team / department canonical data
# Kept here for the backfill data migration (users/0039) which reads it to
# map old group membership → new Department records. Can be removed once
# all environments have run that migration.
# ---------------------------------------------------------------------------

TEAM_CHOICES: list[tuple[str, str]] = [
    ('machining',          'Talaşlı İmalat'),
    ('design',             'Dizayn'),
    ('logistics',          'Lojistik'),
    ('procurement',        'Satın Alma'),
    ('welding',            'Kaynaklı İmalat'),
    ('planning',           'Planlama'),
    ('manufacturing',      'İmalat'),
    ('maintenance',        'Bakım'),
    ('rollingmill',        'Haddehane'),
    ('qualitycontrol',     'Kalite Kontrol'),
    ('cutting',            'CNC Kesim'),
    ('warehouse',          'Ambar'),
    ('finance',            'Finans'),
    ('management',         'Yönetim'),
    ('external_workshops', 'Dış Atölyeler'),
    ('human_resouces',     'İnsan Kaynakları'),  # kept with original typo for group-name compat
    ('sales',              'Proje Taahhüt'),
    ('accounting',         'Muhasebe'),
]

# Maps old group names → department codes.
# Used ONLY by the backfill migration to determine which department
# a user belongs to based on their current Django group membership.
GROUP_TO_DEPT: dict[str, str] = {
    'machining_team':         'machining',
    'design_team':            'design',
    'logistics_team':         'logistics',
    'procurement_team':       'procurement',
    'welding_team':           'welding',
    'planning_team':          'planning',
    'planning_manager':       'planning',
    'manufacturing_team':     'manufacturing',
    'maintenance_team':       'maintenance',
    'qualitycontrol_team':    'qualitycontrol',
    'cutting_team':           'cutting',
    'warehouse_team':         'warehouse',
    'finance_team':           'finance',
    'accounting_team':        'accounting',
    'management_team':        'management',
    'hr_team':                'human_resources',
    'sales_team':             'sales',
    'external_workshops_team':'external_workshops',
}

# ---------------------------------------------------------------------------
# Active helpers (used in production code)
# ---------------------------------------------------------------------------

def get_dept_code_for_user(user: User) -> str | None:
    """
    Return the department code for a user via their assigned Position.
    Returns None if no position is set.
    """
    try:
        pos = user.profile.position
        if pos:
            return pos.department_code or None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Compatibility shims — remove after all callers are migrated
# These replace the old group-based helpers with position-based equivalents.
# ---------------------------------------------------------------------------

TEAM_LABELS: dict[str, str] = dict(TEAM_CHOICES)

# Reverse of TEAM_TO_GROUP below — kept for compat (overtime/serializers.py)
GROUP_TO_TEAM: dict[str, str] = {
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
    'hr_team':                 'human_resouces',
    'sales_team':              'sales',
    'external_workshops_team': 'external_workshops',
}

# Kept for callers that still read it (notifications, procurement)
TEAM_TO_GROUP: dict[str, str] = {
    'machining':          'machining_team',
    'design':             'design_team',
    'logistics':          'logistics_team',
    'procurement':        'procurement_team',
    'welding':            'welding_team',
    'planning':           'planning_team',
    'manufacturing':      'manufacturing_team',
    'maintenance':        'maintenance_team',
    'rollingmill':        'manufacturing_team',
    'qualitycontrol':     'qualitycontrol_team',
    'cutting':            'cutting_team',
    'warehouse':          'warehouse_team',
    'finance':            'finance_team',
    'management':         'management_team',
    'external_workshops': 'procurement_team',
    'human_resouces':     'hr_team',
    'sales':              'sales_team',
    'accounting':         'accounting_team',
}


def primary_team_from_groups(user: User) -> str | None:
    """
    Return the user's primary department code from their Position.
    Replaces the old group-membership-based implementation.
    """
    return get_dept_code_for_user(user)


def users_in_team(team_code: str):
    """
    Return active users in the named department.
    Replaces the old Group-based users_in_team().
    """
    from organization.services import get_dept_members
    return get_dept_members(team_code)


def _team_manager_user_ids(team_code: str) -> list[int]:
    """
    Return IDs of users at manager level (level <= 4) in the given department.
    """
    if not team_code:
        return []
    return list(
        User.objects.filter(
            is_active=True,
            profile__position__department_code=team_code,
            profile__position__level__lte=4,
            profile__position__is_active=True,
        ).values_list('id', flat=True)
    )


def sync_user_group(user: User, team_code: str) -> None:
    """
    No-op shim. Group sync is replaced by organization.signals.
    Kept for seed_users management command compatibility.
    """
    pass
