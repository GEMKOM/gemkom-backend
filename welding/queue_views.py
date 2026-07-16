# welding/queue_views.py
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from machining.permissions import HasQueueSecret
from welding.models import WeldingJobCostRecalcQueue
from welding.services.costing import recompute_welding_job_cost

logger = logging.getLogger(__name__)


class DrainWeldingCostQueueView(APIView):
    """
    Internal endpoint to drain the welding job cost recalculation queue.
    Should be called by a scheduled task (Cloud Scheduler).

    Security: Requires X-Queue-Secret header matching QUEUE_SECRET setting.

    A bounded batch is fetched once and each job_no is processed at most once
    per request, in its own transaction. A job_no whose recompute raises is
    logged and left in the queue for the next run — it can never spin the loop
    or pin the CPU (this endpoint previously infinite-looped on any failing row).
    """
    authentication_classes = []
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get("max", 200))

        job_nos = list(
            WeldingJobCostRecalcQueue.objects
            .order_by("enqueued_at")
            .values_list("job_no", flat=True)[:max_rows]
        )

        processed = 0
        failed = 0
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
                        # Row is gone or held by another worker — skip it.
                        continue
                    recompute_welding_job_cost(job_no)
                    WeldingJobCostRecalcQueue.objects.filter(pk=job_no).delete()
                processed += 1
            except Exception:
                logger.exception(
                    "welding cost recompute failed for job_no=%s; left in queue",
                    job_no,
                )
                failed += 1

        return Response({"processed": processed, "failed": failed})
