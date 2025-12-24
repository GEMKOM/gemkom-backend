# welding/management/commands/recompute_welding_job_costs.py
from django.core.management.base import BaseCommand
from django.db.models import Count

from welding.models import WeldingTimeEntry
from welding.services.costing import recompute_welding_job_cost


class Command(BaseCommand):
    help = "Recompute all welding job costs immediately (for initial population)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--job-no',
            type=str,
            default=None,
            help='Recompute costs for a specific job_no only'
        )

    def handle(self, *args, **opts):
        job_no_filter = opts.get('job_no')

        if job_no_filter:
            # Recompute a specific job
            try:
                recompute_welding_job_cost(job_no_filter)
                self.stdout.write(
                    self.style.SUCCESS(f"Recomputed costs for job: {job_no_filter}")
                )
            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Failed to recompute {job_no_filter}: {e}")
                )
            return

        # Recompute all jobs
        job_nos = (
            WeldingTimeEntry.objects
            .values('job_no')
            .annotate(count=Count('id'))
            .order_by('job_no')
        )

        total = job_nos.count()
        processed = 0
        failed = 0

        self.stdout.write(f"Found {total} distinct job_nos to process...")

        for row in job_nos:
            job_no = row['job_no']
            if not job_no:
                continue

            try:
                recompute_welding_job_cost(job_no)
                processed += 1
                if processed % 10 == 0:
                    self.stdout.write(f"Processed {processed}/{total}...")
            except Exception as e:
                failed += 1
                self.stderr.write(f"Failed {job_no}: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCompleted! Processed: {processed}, Failed: {failed}, Total: {total}"
            )
        )
