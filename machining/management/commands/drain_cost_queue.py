# machining/management/commands/drain_cost_queue.py
from django.core.management.base import BaseCommand
from django.db import transaction

from machining.models import JobCostRecalcQueue
from machining.services.costing import recompute_job_cost_snapshot

class Command(BaseCommand):
    help = "Drains job_cost_recalc_queue and recomputes job cost snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=100)

    def handle(self, *args, **opts):
        batch = opts["batch"]
        processed = 0

        while True:
            # lock a batch (skip locked allows multiple workers)
            with transaction.atomic():
                pending = (
                    JobCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by("enqueued_at")[:batch]
                )
                jobs = list(pending)
                if not jobs:
                    break
                # don't delete yet; if we crash, they’ll remain for next run

            for row in jobs:
                try:
                    recompute_job_cost_snapshot(row.job_no)
                    processed += 1
                    # delete after successful recompute
                    JobCostRecalcQueue.objects.filter(job_no=row.job_no).delete()
                except Exception as e:
                    # leave in queue; next run will retry
                    self.stderr.write(f"Failed {row.job_no}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Processed {processed} jobs"))
