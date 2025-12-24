# welding/queue_views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from machining.permissions import HasQueueSecret
from welding.models import WeldingJobCostRecalcQueue
from welding.services.costing import recompute_welding_job_cost


class DrainWeldingCostQueueView(APIView):
    """
    Internal endpoint to drain the welding job cost recalculation queue.
    Should be called by a scheduled task (cron/celery).

    Security: Requires X-Queue-Secret header matching QUEUE_SECRET setting.
    """
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get("max", 200))
        processed = 0

        while processed < max_rows:
            with transaction.atomic():
                rows = list(
                    WeldingJobCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by("enqueued_at")[:max_rows - processed]
                )
                if not rows:
                    break

            for r in rows:
                try:
                    recompute_welding_job_cost(r.job_no)
                    WeldingJobCostRecalcQueue.objects.filter(job_no=r.job_no).delete()
                    processed += 1
                except Exception as e:
                    # Leave in queue for retry on next run
                    pass

        return Response({"processed": processed})
