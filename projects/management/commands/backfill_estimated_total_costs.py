from django.core.management.base import BaseCommand

from projects.models import JobOrderCostSummary
from projects.services.costing import _store_estimated_total_cost


class Command(BaseCommand):
    help = 'Recompute and store estimated_total_cost for all job orders with a cost summary.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--job-no',
            dest='job_no',
            help='Backfill a single job order only',
        )

    def handle(self, *args, **options):
        job_no = options.get('job_no')
        if job_no:
            job_nos = [job_no]
        else:
            job_nos = list(
                JobOrderCostSummary.objects
                .filter(cost_not_applicable=False)
                .values_list('job_order_id', flat=True)
                .order_by('job_order_id')
            )

        total = len(job_nos)
        for index, current_job_no in enumerate(job_nos, start=1):
            _store_estimated_total_cost(current_job_no)
            if index % 25 == 0 or index == total:
                self.stdout.write(f'Processed {index}/{total}')

        self.stdout.write(self.style.SUCCESS(f'Backfilled estimated_total_cost for {total} job(s).'))
