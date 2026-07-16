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
        failed = 0
        failed_jobs = set()
        skipped_jobs = set()

        # Drain the whole queue in batches. Rows that fail recompute are recorded
        # and rows locked by another worker are skipped for this invocation.
        # Excluding both prevents either kind of row from keeping the batch
        # non-empty and spinning this loop forever.
        while True:
            job_nos = list(
                WeldingJobCostRecalcQueue.objects
                .exclude(job_no__in=failed_jobs | skipped_jobs)
                .order_by("enqueued_at")
                .values_list("job_no", flat=True)[:batch]
            )
            if not job_nos:
                break

            for job_no in job_nos:
                try:
                    with transaction.atomic():
                        locked = (
                            WeldingJobCostRecalcQueue.objects
                            .select_for_update(skip_locked=True)
                            .filter(pk=job_no)
                            .first()
                        )
                        if locked is None:
                            skipped_jobs.add(job_no)
                            continue
                        recompute_welding_job_cost(job_no)
                        WeldingJobCostRecalcQueue.objects.filter(pk=job_no).delete()
                    processed += 1
                except Exception as e:
                    failed += 1
                    failed_jobs.add(job_no)
                    self.stderr.write(f"Failed {job_no}: {e}")

        self.stdout.write(
            self.style.SUCCESS(f"Processed {processed} welding jobs, {failed} failed")
        )
