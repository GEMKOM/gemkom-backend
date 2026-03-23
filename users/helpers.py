# ------- Helpers -------
from django.contrib.auth.models import User
from django.db.models import Q

TEAM_MANAGER_OCCUPATION = "manager"

# Maps legacy profile.team codes to Django Group names.
TEAM_TO_GROUP: dict[str, str] = {
    'machining':        'machining_team',
    'design':           'design_team',
    'logistics':        'logistics_team',
    'procurement':      'procurement_team',
    'welding':          'welding_team',
    'planning':         'planning_team',
    'manufacturing':    'manufacturing_team',
    'maintenance':      'maintenance_team',
    'rollingmill':      'manufacturing_team',
    'qualitycontrol':   'qualitycontrol_team',
    'cutting':          'cutting_team',
    'warehouse':        'warehouse_team',
    'finance':          'finance_team',
    'management':       'management_team',
    'external_workshops': 'procurement_team',
    'human_resouces':   'hr_team',
    'sales':            'sales_team',
    'accounting':       'accounting_team',
}

# Teams that have a dedicated manager group in addition to occupation-based detection.
TEAM_TO_MANAGER_GROUP: dict[str, str] = {
    'planning': 'planning_manager',
}


def users_in_team(team: str):
    """Return active users belonging to the group that corresponds to the given team code."""
    group_name = TEAM_TO_GROUP.get(team)
    if not group_name:
        return User.objects.none()
    return User.objects.filter(is_active=True, groups__name=group_name)


def _team_manager_user_ids(team: str) -> list[int]:
    """
    Return IDs of active managers for the given team code.
    Checks both occupation='manager' within the team group, and any dedicated
    manager group (e.g. planning_manager).
    """
    if not team:
        return []
    group_name = TEAM_TO_GROUP.get(team)
    if not group_name:
        return []

    q = Q(is_active=True, groups__name=group_name, profile__occupation=TEAM_MANAGER_OCCUPATION)

    manager_group = TEAM_TO_MANAGER_GROUP.get(team)
    if manager_group:
        q |= Q(is_active=True, groups__name=manager_group)

    return list(User.objects.filter(q).values_list("id", flat=True).distinct())
