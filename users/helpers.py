# ------- Helpers -------
from django.contrib.auth.models import User
from django.db.models import Q

TEAM_MANAGER_OCCUPATION = "manager"

# Canonical team code → display label mapping.
# Previously lived on UserProfile.TEAM_CHOICES; centralised here after field removal.
TEAM_CHOICES: list[tuple[str, str]] = [
    ('machining',         'Talaşlı İmalat'),
    ('design',            'Dizayn'),
    ('logistics',         'Lojistik'),
    ('procurement',       'Satın Alma'),
    ('welding',           'Kaynaklı İmalat'),
    ('planning',          'Planlama'),
    ('manufacturing',     'İmalat'),
    ('maintenance',       'Bakım'),
    ('rollingmill',       'Haddehane'),
    ('qualitycontrol',    'Kalite Kontrol'),
    ('cutting',           'CNC Kesim'),
    ('warehouse',         'Ambar'),
    ('finance',           'Finans'),
    ('management',        'Yönetim'),
    ('external_workshops','Dış Atölyeler'),
    ('human_resouces',    'İnsan Kaynakları'),
    ('sales',             'Proje Taahhüt'),
    ('accounting',        'Muhasebe'),
]
TEAM_LABELS: dict[str, str] = dict(TEAM_CHOICES)

# Maps team codes to Django Group names.
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

# Reverse map: group name → team code (first match wins for multi-team groups like rollingmill)
GROUP_TO_TEAM: dict[str, str] = {}
for _team, _group in TEAM_TO_GROUP.items():
    if _group not in GROUP_TO_TEAM:
        GROUP_TO_TEAM[_group] = _team


def primary_team_from_groups(user) -> str | None:
    """Return the team code for the user's primary team group, or None."""
    for group in user.groups.all():
        team = GROUP_TO_TEAM.get(group.name)
        if team:
            return team
    return None


def sync_user_group(user, team: str | None) -> None:
    """
    Set the user's team group to match the given team code.
    Removes any existing team groups first, then adds the new one.
    """
    from django.contrib.auth.models import Group

    old_team_groups = [g for g in user.groups.all() if g.name in GROUP_TO_TEAM]
    for g in old_team_groups:
        user.groups.remove(g)

    if team:
        group_name = TEAM_TO_GROUP.get(team)
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
            # Also add dedicated manager group if occupation matches
            manager_group_name = TEAM_TO_MANAGER_GROUP.get(team)
            if manager_group_name:
                profile_occupation = getattr(getattr(user, 'profile', None), 'occupation', None)
                if profile_occupation == TEAM_MANAGER_OCCUPATION:
                    manager_group, _ = Group.objects.get_or_create(name=manager_group_name)
                    user.groups.add(manager_group)


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
