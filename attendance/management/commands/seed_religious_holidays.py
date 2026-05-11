"""
Management command to seed Turkish Islamic (lunar) public holidays.

Nager.Date does not include religious holidays because they follow the Hijri
(Islamic lunar) calendar and their Gregorian dates shift ~11 days earlier each year.
This command calculates them using the standard astronomical Hijri-to-Gregorian
algorithm and inserts them into the same PublicHoliday table.

Turkish religious holidays:
  Ramazan Bayramı (Eid al-Fitr)  — starts 1 Shawwal:  1 day holiday + "Arife" eve
  Kurban Bayramı  (Eid al-Adha)  — starts 10 Dhu al-Hijja: 4 days + "Arife" eve

In Turkish law both bayrams include an "Arife" half-day before the first day,
but for simplicity we seed Arife as a full public holiday (matching official practice).

Usage:
    python manage.py seed_religious_holidays               # seeds 2020–2055
    python manage.py seed_religious_holidays --start 2026 --end 2030
    python manage.py seed_religious_holidays --year 2026   # single year
    python manage.py seed_religious_holidays --dry-run
"""

import math
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from attendance.models import PublicHoliday

DEFAULT_START = 2020
DEFAULT_END   = 2055


# ---------------------------------------------------------------------------
# Hijri → Gregorian conversion
# Uses Watt's formula via Julian Day Numbers — matches Turkish Diyanet dates.
# ---------------------------------------------------------------------------

def _hijri_to_jd(hy: int, hm: int, hd: int) -> int:
    return (
        math.floor((11 * hy + 3) / 30)
        + 354 * hy
        + 30 * hm
        - math.floor((hm - 1) / 2)
        + hd
        + 1948440
        - 385
    )


def _jd_to_gregorian(jd: int) -> date:
    l = jd + 68569
    n = math.floor(4 * l / 146097)
    l -= math.floor((146097 * n + 3) / 4)
    i = math.floor(4000 * (l + 1) / 1461001)
    l -= math.floor(1461 * i / 4) - 31
    j = math.floor(80 * l / 2447)
    d = l - math.floor(2447 * j / 80)
    l = math.floor(j / 11)
    m = j + 2 - 12 * l
    y = 100 * (n - 49) + i + l
    return date(y, m, d)


def _hijri_to_gregorian(hy: int, hm: int, hd: int) -> date:
    return _jd_to_gregorian(_hijri_to_jd(hy, hm, hd))


def _eid_al_fitr(gregorian_year: int) -> date | None:
    """
    Return the Gregorian date of 1 Shawwal (Eid al-Fitr) in the given
    Gregorian year. Returns None if it doesn't fall within that year.
    """
    # Approximate Hijri year range that overlaps this Gregorian year
    h_year_approx = gregorian_year - 579  # rough offset
    for h_year in range(h_year_approx - 1, h_year_approx + 2):
        g_date = _hijri_to_gregorian(h_year, 10, 1)  # 1 Shawwal
        if g_date.year == gregorian_year:
            return g_date
    return None


def _eid_al_adha(gregorian_year: int) -> date | None:
    """
    Return the Gregorian date of 10 Dhu al-Hijja (Eid al-Adha) in the
    given Gregorian year. Returns None if it doesn't fall within that year.
    """
    h_year_approx = gregorian_year - 579
    for h_year in range(h_year_approx - 1, h_year_approx + 2):
        g_date = _hijri_to_gregorian(h_year, 12, 10)  # 10 Dhu al-Hijja
        if g_date.year == gregorian_year:
            return g_date
    return None


def religious_holidays_for_year(gregorian_year: int) -> list[tuple[date, str, str, bool]]:
    """
    Return a list of (date, name_en, local_name_tr, is_half_day) tuples for all
    Turkish religious public holidays in the given Gregorian year.

    Ramazan Bayramı: Arife (half-day) + 3 full days  = 4 entries
    Kurban Bayramı:  Arife (half-day) + 4 full days  = 5 entries

    Note: It is possible (though rare) for a bayram to straddle two Gregorian
    years. In such cases only the days that fall in `gregorian_year` are
    returned; call the function for both years to get all days.
    """
    entries: list[tuple[date, str, str, bool]] = []

    eid_fitr = _eid_al_fitr(gregorian_year)
    if eid_fitr:
        arife = eid_fitr - timedelta(days=1)
        if arife.year == gregorian_year:
            entries.append((arife, "Eid al-Fitr Eve (Arife)", "Ramazan Bayramı Arifesi", True))
        for i in range(3):
            d = eid_fitr + timedelta(days=i)
            if d.year == gregorian_year:
                day_num = i + 1
                entries.append((
                    d,
                    f"Eid al-Fitr – Day {day_num}",
                    f"Ramazan Bayramı ({day_num}. Gün)",
                    False,
                ))

    eid_adha = _eid_al_adha(gregorian_year)
    if eid_adha:
        arife = eid_adha - timedelta(days=1)
        if arife.year == gregorian_year:
            entries.append((arife, "Eid al-Adha Eve (Arife)", "Kurban Bayramı Arifesi", True))
        for i in range(4):
            d = eid_adha + timedelta(days=i)
            if d.year == gregorian_year:
                day_num = i + 1
                entries.append((
                    d,
                    f"Eid al-Adha – Day {day_num}",
                    f"Kurban Bayramı ({day_num}. Gün)",
                    False,
                ))

    return entries


# ---------------------------------------------------------------------------
# Management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Seed Turkish Islamic (lunar-calendar) religious holidays into the "
        "PublicHoliday table. Safe to re-run — uses update_or_create."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start", type=int, default=DEFAULT_START)
        parser.add_argument("--end",   type=int, default=DEFAULT_END)
        parser.add_argument("--year",  type=int, help="Single year (overrides --start/--end)")
        parser.add_argument("--dry-run", action="store_true", help="Print without saving.")

    def handle(self, *args, **options):
        if options["year"]:
            years = [options["year"]]
        else:
            years = range(options["start"], options["end"] + 1)

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved."))

        total_created = total_updated = 0

        for year in years:
            holidays = religious_holidays_for_year(year)
            created = updated = 0
            for g_date, name_en, local_name, is_half_day in holidays:
                half_tag = " [Arife/Yarım Gün]" if is_half_day else ""
                label = f"  {'[DRY]' if dry_run else ''} {g_date}  {local_name}{half_tag}"
                if not dry_run:
                    _, was_created = PublicHoliday.objects.update_or_create(
                        date=g_date,
                        defaults={"name": name_en, "local_name": local_name, "is_half_day": is_half_day},
                    )
                    if was_created:
                        created += 1
                        label += "  [CREATED]"
                    else:
                        updated += 1
                        label += "  [UPDATED]"
                self.stdout.write(label)

            if not dry_run:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {year}: {created} created, {updated} updated"
                    )
                )
            total_created += created
            total_updated += updated

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Total: {total_created} created, {total_updated} updated."
            )
        )
