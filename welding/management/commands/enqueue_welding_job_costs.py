# welding/management/commands/enqueue_welding_job_costs.py
from django.core.management.base import BaseCommand
from django.db.models import Count

from welding.models import WeldingTimeEntry, WeldingJobCostRecalcQueue


class Command(BaseCommand):
    help = "Enqueue all job_nos from WeldingTimeEntry for cost recalculation."

    def handle(self, *args, **opts):
        # Get distinct job_nos from all welding time entries
        job_nos = (
            WeldingTimeEntry.objects
            .values('job_no')
            .annotate(count=Count('id'))
            .order_by('job_no')
        )

        enqueued = 0
        for row in job_nos:
            job_no = row['job_no']
            if job_no:
                WeldingJobCostRecalcQueue.objects.update_or_create(
                    job_no=job_no,
                    defaults={}
                )
                enqueued += 1

        self.stdout.write(
            self.style.SUCCESS(f"Enqueued {enqueued} welding jobs for cost recalculation")
        )
