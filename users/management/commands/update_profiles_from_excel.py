import datetime
import os

import xlrd
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from users.models import UserProfile

User = get_user_model()

GENDER_MAP = {
    "erkek": "M",
    "kadın": "F",
    "kadin": "F",
}

SIGORTA_MAP = {
    "normal": "normal",
    "emekli": "emekli",
}


def _xls_date(value):
    if not value:
        return None
    try:
        return datetime.date(*xlrd.xldate_as_tuple(value, 0)[:3])
    except Exception:
        return None


class Command(BaseCommand):
    help = "Update UserProfile fields from personel listesi-gemcore.xls"

    def add_arguments(self, parser):
        parser.add_argument(
            "--xls",
            default=os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))))),
                "personel listesi-gemcore.xls",
            ),
            help="Path to the XLS file (default: project root)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without saving",
        )

    def handle(self, *args, **options):
        xls_path = options["xls"]
        dry_run = options["dry_run"]

        if not os.path.exists(xls_path):
            self.stderr.write(f"File not found: {xls_path}")
            return

        wb = xlrd.open_workbook(xls_path)
        sh = wb.sheet_by_index(0)

        updated = skipped_no_user = not_found = 0

        for i in range(1, sh.nrows):
            row = sh.row_values(i)
            # col: 0=personel_kodu 1=name 2=username 3=tc 4=giris
            #      5=cinsiyet 6=ucret_tipi 7=hesaplama 8=ucreti 9=sigorta 10=dogum
            raw_username = row[2]
            if not isinstance(raw_username, str) or not raw_username.strip():
                skipped_no_user += 1
                continue

            username = raw_username.strip()

            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"  [NOT FOUND] {username}"))
                not_found += 1
                continue

            profile, _ = UserProfile.objects.get_or_create(user=user)

            personel_kodu       = str(row[0]).strip() if row[0] else None
            tc_kimlik_no        = str(int(row[3])) if row[3] else None
            gender              = GENDER_MAP.get(str(row[5]).strip().lower())
            sigorta_yuzde_grubu = SIGORTA_MAP.get(str(row[9]).strip().lower())
            hire_date           = _xls_date(row[4])
            birth_date          = _xls_date(row[10])

            if dry_run:
                self.stdout.write(
                    f"  [DRY RUN] {username} -> kodu={personel_kodu} tc={tc_kimlik_no} "
                    f"gender={gender} sigorta={sigorta_yuzde_grubu} "
                    f"hire={hire_date} birth={birth_date}"
                )
            else:
                profile.personel_kodu       = personel_kodu
                profile.tc_kimlik_no        = tc_kimlik_no
                profile.gender              = gender
                profile.sigorta_yuzde_grubu = sigorta_yuzde_grubu
                profile.hire_date           = hire_date
                profile.birth_date          = birth_date
                profile.save(update_fields=[
                    "personel_kodu", "tc_kimlik_no", "gender",
                    "sigorta_yuzde_grubu", "hire_date", "birth_date",
                ])
                self.stdout.write(self.style.SUCCESS(f"  [OK] {username} -> {personel_kodu}"))

            updated += 1

        self.stdout.write(
            f"\nDone. updated={updated}, skipped_no_username={skipped_no_user}, not_found_in_db={not_found}"
        )
