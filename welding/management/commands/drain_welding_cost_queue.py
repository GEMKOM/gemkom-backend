# welding/management/commands/drain_welding_cost_queue.py
from django.core.management.base import BaseCommand
from django.db import transaction

from welding.models import WeldingJobCostRecalcQueue
from welding.services.costing import recompute_welding_job_cost


class Command(BaseCommand):
    help = "Drains welding_job_cost_recalc_queue and recomputes job cost snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=100)

    def handle(self, *args, **opts):
        batch = opts["batch"]
        processed = 0

        while True:
            # lock a batch (skip locked allows multiple workers)
            with transaction.atomic():
                jobs = list(
                    WeldingJobCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by("enqueued_at")[:batch]
                )
                if not jobs:
                    break
                # don't delete yet; if we crash, they'll remain for next run

            for row in jobs:
                try:
                    recompute_welding_job_cost(row.job_no)
                    processed += 1
                    # delete after successful recompute
                    WeldingJobCostRecalcQueue.objects.filter(job_no=row.job_no).delete()
                except Exception as e:
                    # leave in queue; next run will retry
                    self.stderr.write(f"Failed {row.job_no}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Processed {processed} welding jobs"))
