from __future__ import annotations
from calendar import monthrange
from datetime import date
from decimal import Decimal

from procurement.reports.common import q2, get_fallback_rates, to_eur

WAGE_MONTH_HOURS = Decimal("225")


def compute_monthly_wage(year: int, month: int) -> dict:
    """
    Estimate total wage cost for a given month in EUR.

    Base payroll: sum of each active employee's WageRate.base_monthly
    (using the latest WageRate with effective_from <= last day of month).

    Overtime premium: approved OvertimeRequests whose period overlaps the month.
    Per entry: approved_hours × (base_monthly / WAGE_MONTH_HOURS) × (multiplier - 1)
    The -1 gives the premium on top of base (base already counted in payroll).
    """
    from django.contrib.auth import get_user_model
    from users.models import WageRate
    from overtime.models import OvertimeRequest, OvertimeEntry

    User = get_user_model()
    fb = get_fallback_rates()

    month_end = date(year, month, monthrange(year, month)[1])
    month_start = date(year, month, 1)

    # Active users with a profile
    active_users = (
        User.objects
        .filter(is_active=True, profile__isnull=False)
        .values_list("id", flat=True)
    )

    # For each user pick the most recent WageRate effective on or before month_end
    wage_map: dict[int, WageRate] = {}
    all_rates = (
        WageRate.objects
        .filter(user_id__in=active_users, effective_from__lte=month_end)
        .order_by("user_id", "-effective_from")
    )
    for rate in all_rates:
        if rate.user_id not in wage_map:
            wage_map[rate.user_id] = rate

    base_payroll_eur = Decimal("0.00")
    employee_count = 0
    for rate in wage_map.values():
        eur = to_eur(rate.base_monthly, rate.currency, {}, fb) or Decimal("0")
        base_payroll_eur += eur
        employee_count += 1

    # Overtime premium
    ot_requests = (
        OvertimeRequest.objects
        .filter(
            status="approved",
            start_at__date__lte=month_end,
            end_at__date__gte=month_start,
        )
        .prefetch_related("entries")
    )

    overtime_premium_eur = Decimal("0.00")
    for req in ot_requests:
        for entry in req.entries.all():
            if entry.approved_hours is None:
                continue
            wage = wage_map.get(entry.user_id)
            if wage is None:
                continue
            hourly = wage.base_monthly / WAGE_MONTH_HOURS
            # after_hours_multiplier - 1 = premium rate (extra on top of base)
            premium = hourly * (wage.after_hours_multiplier - Decimal("1")) * entry.approved_hours
            eur = to_eur(premium, wage.currency, {}, fb) or Decimal("0")
            overtime_premium_eur += eur

    return {
        "base_payroll_eur": str(q2(base_payroll_eur)),
        "overtime_premium_eur": str(q2(overtime_premium_eur)),
        "total_eur": str(q2(base_payroll_eur + overtime_premium_eur)),
        "employee_count": employee_count,
    }


def expense_applies_to_month(expense, year: int, month: int) -> bool:
    """
    Returns True if a MonthlyExpense recurrence lands in the given month.
    """
    from dateutil.relativedelta import relativedelta

    s = expense.start_date
    if s.year > year or (s.year == year and s.month > month):
        return False

    end = expense.end_date
    if end and (end.year < year or (end.year == year and end.month < month)):
        return False

    recurrence = expense.recurrence
    if recurrence == "once":
        return s.year == year and s.month == month
    if recurrence == "monthly":
        return True
    if recurrence == "quarterly":
        months_since = (year - s.year) * 12 + (month - s.month)
        return months_since % 3 == 0
    if recurrence == "annual":
        return month == s.month
    return False
