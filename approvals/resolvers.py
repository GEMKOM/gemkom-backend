from __future__ import annotations


def resolve_approvers_for_stage(stage, requester) -> list[int]:
    """
    Unified approver resolution for an ApprovalStage.

    Priority order:
      1. stage.approver_users (static — directors, explicit assignments)
      2. stage.role_department_code → all active users in that department
      3. stage.climb_levels → walk requester's position chain N levels up

    Returns a deduplicated list of user IDs, preserving insertion order.
    """
    user_ids: list[int] = list(stage.approver_users.values_list('id', flat=True))

    if stage.role_department_code:
        from organization.services import get_dept_members
        dept_ids = list(
            get_dept_members(stage.role_department_code)
            .values_list('id', flat=True)
        )
        user_ids += dept_ids

    elif stage.climb_levels is not None and requester is not None:
        try:
            position = requester.profile.position
        except Exception:
            position = None

        if position:
            from organization.services import resolve_chain_approvers
            chain_ids = resolve_chain_approvers(position, stage.climb_levels)
            user_ids += chain_ids

    return list(dict.fromkeys(user_ids))
