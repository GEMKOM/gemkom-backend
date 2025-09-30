from __future__ import annotations
from datetime import datetime
from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import make_aware, get_default_timezone

from machining.models import Timer, JobCostRecalcQueue
from machining.services.costing import recompute_task_cost_snapshot


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
        "Enqueue tasks (by task_id) for job-cost recomputation. "
        "Scans timers and collects distinct issue_key_id. "
        "Supports date filters and an optional immediate recompute."
    )

    def add_arguments(self, parser):
        parser.add_argument("--since", type=str, default=None, help="YYYY-MM-DD (local). Include timers starting on/after this date.")
        parser.add_argument("--until", type=str, default=None, help="YYYY-MM-DD (local). Include timers starting on/before this date.")
        parser.add_argument("--limit", type=int, default=None, help="Limit number of tasks.")
        parser.add_argument("--batch", type=int, default=500, help="Bulk-create batch size. Default 500.")
        parser.add_argument("--recompute", action="store_true", help="Immediately recompute each task snapshot after enqueueing.")

    def handle(self, *args, **opts):
        tz = get_default_timezone()

        since = self._parse_local_date(opts.get("since"))
        until = self._parse_local_date(opts.get("until"))
        limit = opts.get("limit")
        batch = int(opts.get("batch") or 500)
        do_recompute = bool(opts.get("recompute"))

        qs = Timer.objects.filter(issue_key_id__isnull=False)

        # Convert date boundaries to epoch-ms (local)
        if since:
            start_ms = int(make_aware(datetime(since.year, since.month, since.day, 0, 0, 0), tz).timestamp() * 1000)
            qs = qs.filter(start_time__gte=start_ms)
        if until:
            end_ms = int(make_aware(datetime(until.year, until.month, until.day, 23, 59, 59), tz).timestamp() * 1000)
            qs = qs.filter(start_time__lte=end_ms)

        task_ids = (
            qs.values_list("issue_key_id", flat=True)
              .distinct()
              .order_by("issue_key_id")
        )
        if limit:
            task_ids = task_ids[:limit]

        task_ids = [t for t in task_ids if t]
        total = len(task_ids)
        if total == 0:
            self.stdout.write(self.style.WARNING("No tasks found to enqueue."))
            return

        self.stdout.write(f"Found {total} tasks. Enqueuing...")
        

        created = 0
        for chunk in chunked(task_ids, batch):
            rows = [JobCostRecalcQueue(task_id=t) for t in chunk]
            with transaction.atomic():
                created += len(JobCostRecalcQueue.objects.bulk_create(rows, ignore_conflicts=True))

        self.stdout.write(self.style.SUCCESS(f"Enqueued {created} task(s) (duplicates ignored)."))

        if do_recompute:
            self.stdout.write("Recomputing snapshots immediately...")
            done = 0
            for t in task_ids:
                try:
                    recompute_task_cost_snapshot(t)
                    done += 1
                except Exception as e:
                    self.stderr.write(f"[FAIL] task_id={t}: {e}")
            self.stdout.write(self.style.SUCCESS(f"Recomputed {done}/{total} task(s)."))

    @staticmethod
    def _parse_local_date(s: str | None):
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            raise SystemExit(f"Invalid date '{s}'. Expected YYYY-MM-DD.")
