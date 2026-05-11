"""
Management command to credit annual leave entitlement on each user's work anniversary.

Run daily via Cloud Scheduler:
    python manage.py credit_annual_leave

Safe to run multiple times — skips users already credited today.

Turkish Labor Law No. 4857, Article 53 entitlements:
    < 1 year service  →  0 days (not yet entitled)
    1–5 years         → 14 days
    5–15 years        → 20 days
    15+ years         → 26 days
    Under 18 or over 50 → minimum 20 days regardless of tenure
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from vacation_requests.models import UserLeaveBalance

User = get_user_model()


def _entitled_days(hire_date: date, today: date, birth_date: date | None = None) -> int:
    """
    Return the annual leave days earned at this anniversary based on completed years of service.
    Returns 0 if less than 1 full year has been completed.
    """
    completed_years = (
        today.year - hire_date.year
        - (1 if (today.month, today.day) < (hire_date.month, hire_date.day) else 0)
    )

    if completed_years < 1:
        return 0

    if completed_years < 5:
        days = 14
    elif completed_years < 15:
        days = 20
    else:
        days = 26

    # Special rule: under 18 or over 50 → minimum 20 days
    if birth_date:
        age = (
            today.year - birth_date.year
            - (1 if (today.month, today.day) < (birth_date.month, birth_date.day) else 0)
        )
        if age < 18 or age > 50:
            days = max(days, 20)

    return days


def _is_anniversary_today(hire_date: date, today: date) -> bool:
    """
    True if today is the user's work anniversary (same month/day as hire, any year after).
    Handles Feb 29 hire dates by crediting on Mar 1 in non-leap years.
    """
    if hire_date >= today:
        return False
    if hire_date.month == 2 and hire_date.day == 29:
        # Leap-day hire: credit on Feb 28 in non-leap years
        if today.month == 2 and today.day == 28 and today.year % 4 != 0:
            return True
        return today.month == 2 and today.day == 29
    return today.month == hire_date.month and today.day == hire_date.day


class Command(BaseCommand):
    help = (
        "Credit annual leave entitlement for users whose work anniversary falls today. "
        "Run daily via Cloud Scheduler. Safe to re-run — skips already-credited users."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Override today's date (YYYY-MM-DD). Useful for backfilling a missed day.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without making any changes.",
        )

    def handle(self, *args, **options):
        today = date.today()
        if options["date"]:
            try:
                today = date.fromisoformat(options["date"])
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Invalid date: {options['date']}. Use YYYY-MM-DD."))
                return

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved."))

        users = (
            User.objects
            .filter(is_active=True, profile__hire_date__isnull=False)
            .select_related("profile")
        )

        credited = 0
        skipped  = 0
        no_anniversary = 0

        for user in users:
            hire_date = user.profile.hire_date

            if not _is_anniversary_today(hire_date, today):
                no_anniversary += 1
                continue

            # Already credited today (idempotency guard)
            balance = UserLeaveBalance.objects.filter(user=user).first()
            if balance and balance.last_credited_date == today:
                self.stdout.write(f"  SKIP (already credited today): {user.username}")
                skipped += 1
                continue

            birth_date = getattr(user.profile, "birth_date", None)
            days = _entitled_days(hire_date, today, birth_date)

            if days == 0:
                no_anniversary += 1
                continue

            completed_years = (
                today.year - hire_date.year
                - (1 if (today.month, today.day) < (hire_date.month, hire_date.day) else 0)
            )

            self.stdout.write(
                f"  {'[DRY RUN] ' if dry_run else ''}CREDIT {user.username}: "
                f"+{days} days (year {completed_years}, hire={hire_date})"
            )

            if not dry_run:
                with transaction.atomic():
                    from vacation_requests.models import LeaveBalanceLog
                    balance, _ = UserLeaveBalance.objects.get_or_create(
                        user=user,
                        defaults={"total_days": Decimal("0"), "used_days": Decimal("0")},
                    )
                    balance.total_days += Decimal(str(days))
                    balance.last_credited_date = today
                    balance.save(update_fields=["total_days", "last_credited_date"])
                    LeaveBalanceLog.objects.create(
                        user=user,
                        kind=LeaveBalanceLog.KIND_ANNIVERSARY,
                        delta=Decimal(str(days)),
                        balance_after=balance.remaining_days,
                        note=f"Yıllık kredi: {completed_years}. yıl dönümü ({hire_date}), +{days} gün",
                    )

            credited += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Credited: {credited} | Already done: {skipped} | No anniversary today: {no_anniversary}"
            )
        )
