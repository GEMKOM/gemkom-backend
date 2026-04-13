"""
Management command to seed Turkish public holidays from Nager.Date API.

Usage:
    python manage.py seed_holidays                  # seeds 2020–2055
    python manage.py seed_holidays --start 2026 --end 2030
    python manage.py seed_holidays --year 2026      # single year
"""
import time
import urllib.request
import json

from django.core.management.base import BaseCommand

from attendance.models import PublicHoliday

NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/TR"
DEFAULT_START = 2020
DEFAULT_END = 2055


class Command(BaseCommand):
    help = "Fetch Turkish public holidays from Nager.Date and store in the database."

    def add_arguments(self, parser):
        parser.add_argument('--start', type=int, default=DEFAULT_START, help="Start year (default: 2020)")
        parser.add_argument('--end', type=int, default=DEFAULT_END, help="End year (default: 2055)")
        parser.add_argument('--year', type=int, help="Fetch a single year (overrides --start/--end)")

    def handle(self, *args, **options):
        if options['year']:
            years = [options['year']]
        else:
            years = range(options['start'], options['end'] + 1)

        total_created = 0
        total_updated = 0

        for year in years:
            self.stdout.write(f"Fetching {year}...", ending=" ")
            url = NAGER_URL.format(year=year)

            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    data = json.loads(response.read().decode())
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"FAILED ({e})"))
                continue

            created = updated = 0
            for entry in data:
                obj, was_created = PublicHoliday.objects.update_or_create(
                    date=entry['date'],
                    defaults={
                        'name': entry.get('name', ''),
                        'local_name': entry.get('localName', ''),
                    }
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            total_created += created
            total_updated += updated
            self.stdout.write(self.style.SUCCESS(f"OK ({created} created, {updated} updated)"))

            # Be polite to the free API — small delay between requests
            time.sleep(0.3)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Total: {total_created} created, {total_updated} updated."
            )
        )
