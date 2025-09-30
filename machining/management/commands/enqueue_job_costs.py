from __future__ import annotations
from datetime import datetime
from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import make_aware, get_default_timezone

from machining.models import Timer, JobCostRecalcQueue
from machining.services.costing import recompute_job_cost_snapshot


def chunked(iterable: Iterable, size: int = 500):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


class Command(BaseCommand):
    help = (
        "Enqueue job numbers for job-cost recomputation. "
        "By default scans all timers with a job_no. "
        "You can filter by date range or job_no prefix, and optionally recompute immediately."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only include timers with start_time >= this ISO date (YYYY-MM-DD) in local TZ.",
        )
        parser.add_argument(
            "--until",
            type=str,
            default=None,
            help="Only include timers with start_time <= this ISO date (YYYY-MM-DD) in local TZ.",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default=None,
            help="Only include job_nos starting with this prefix (e.g., J-1).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of distinct job_nos to enqueue.",
        )
        parser.add_argument(
            "--recompute",
            action="store_true",
            help="After enqueuing, immediately recompute each job snapshot (bypasses the queue worker).",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Bulk-create batch size for enqueue (default: 500).",
        )

    def handle(self, *args, **opts):
        tz = get_default_timezone()

        since = self._parse_local_date(opts.get("since"), tz)
        until = self._parse_local_date(opts.get("until"), tz)
        prefix = opts.get("prefix")
        limit = opts.get("limit")
        batch = int(opts.get("batch") or 500)
        do_recompute = bool(opts.get("recompute"))

        qs = Timer.objects.select_related("issue_key").filter(issue_key__job_no__isnull=False)

        # Convert ISO date boundaries to epoch-ms bounds against Timer.start_time
        if since:
            # inclusive start-of-day (local) → ms
            start_ms = int(make_aware(datetime(since.year, since.month, since.day, 0, 0, 0), tz).timestamp() * 1000)
            qs = qs.filter(start_time__gte=start_ms)
        if until:
            # inclusive end-of-day (local) → ms
            end_ms = int(make_aware(datetime(until.year, until.month, until.day, 23, 59, 59), tz).timestamp() * 1000)
            qs = qs.filter(start_time__lte=end_ms)

        if prefix:
            qs = qs.filter(issue_key__job_no__startswith=prefix)

        job_nos = (
            qs.values_list("issue_key__job_no", flat=True)
              .distinct()
              .order_by("issue_key__job_no")
        )
        if limit:
            job_nos = job_nos[:limit]

        job_nos = [j for j in job_nos if j]  # guard against empty strings
        total = len(job_nos)
        if total == 0:
            self.stdout.write(self.style.WARNING("No jobs found to enqueue."))
            return

        self.stdout.write(f"Found {total} jobs. Enqueuing...")

        # Enqueue with bulk_create(ignore_conflicts=True) for speed/idempotency
        created = 0
        for chunk in chunked(job_nos, batch):
            rows = [JobCostRecalcQueue(job_no=j) for j in chunk]
            with transaction.atomic():
                created += len(JobCostRecalcQueue.objects.bulk_create(rows, ignore_conflicts=True))

        self.stdout.write(self.style.SUCCESS(f"Enqueued {created} job(s) (duplicates ignored)."))

        if do_recompute:
            self.stdout.write("Recomputing snapshots immediately (this may take a while)...")
            done = 0
            for j in job_nos:
                try:
                    recompute_job_cost_snapshot(j)
                    done += 1
                except Exception as e:
                    self.stderr.write(f"[FAIL] {j}: {e}")
            self.stdout.write(self.style.SUCCESS(f"Recomputed {done}/{total} job(s)."))

    @staticmethod
    def _parse_local_date(s: str | None, tz):
        if not s:
            return None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d").date()
            return dt
        except ValueError:
            raise SystemExit(f"Invalid date '{s}'. Expected YYYY-MM-DD.")
