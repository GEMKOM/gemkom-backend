# ------- Helpers -------
from django.contrib.auth.models import User

TEAM_MANAGER_OCCUPATION = "manager"

def _team_manager_user_ids(team: str) -> list[int]:
    if not team:
        return []
    return list(
        User.objects.filter(
            is_active=True,
            profile__team=team,
            profile__occupation=TEAM_MANAGER_OCCUPATION,
        ).values_list("id", flat=True)
    )