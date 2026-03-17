# ------- Helpers -------
from django.contrib.auth.models import User

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


def users_in_team(team: str):
    """Return active users belonging to the group that corresponds to the given team code."""
    group_name = TEAM_TO_GROUP.get(team)
    if not group_name:
        return User.objects.none()
    return User.objects.filter(is_active=True, groups__name=group_name)


def _team_manager_user_ids(team: str) -> list[int]:
    if not team:
        return []
    group_name = TEAM_TO_GROUP.get(team)
    if not group_name:
        return []
    return list(
        User.objects.filter(
            is_active=True,
            groups__name=group_name,
            profile__occupation=TEAM_MANAGER_OCCUPATION,
        ).values_list("id", flat=True)
    )
