import logging

from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from machining.permissions import HasQueueSecret
from subcontracting.models import SubcontractorCostRecalcQueue
from subcontracting.services.costing import recompute_subcontractor_cost

logger = logging.getLogger(__name__)


class DrainSubcontractorCostQueueView(APIView):
    """
    Internal endpoint for processing the subcontractor cost recalculation queue.
    Called by background workers (Cloud Run scheduler).

    POST /subcontracting/internal/drain-cost-queue/
    Headers: X-Queue-Secret: <secret>
    Body: {"max": 200}  (optional, default 200)
    Response: {"processed": N, "failed": M}

    A bounded batch is fetched once and each job_no is processed at most once per
    request, in its own transaction. A job_no whose recompute raises is logged
    and left in the queue for the next run — it is no longer deleted on failure
    (which silently dropped the recalculation) and can never spin the CPU.
    """
    authentication_classes = []
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get('max', 200))

        job_nos = list(
            SubcontractorCostRecalcQueue.objects
            .order_by('enqueued_at')
            .values_list('job_no', flat=True)[:max_rows]
        )

        processed = 0
        failed = 0
        for job_no in job_nos:
            try:
                with transaction.atomic():
                    locked = (
                        SubcontractorCostRecalcQueue.objects
                        .select_for_update(skip_locked=True)
                        .filter(pk=job_no)
                        .first()
                    )
                    if locked is None:
                        # Row is gone or held by another worker — skip it.
                        continue
                    recompute_subcontractor_cost(job_no)
                    SubcontractorCostRecalcQueue.objects.filter(pk=job_no).delete()
                processed += 1
            except Exception:
                logger.exception(
                    "subcontractor cost recompute failed for job_no=%s; left in queue",
                    job_no,
                )
                failed += 1

        return Response({'processed': processed, 'failed': failed})
