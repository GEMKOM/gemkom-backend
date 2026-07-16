import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from machining.permissions import HasQueueSecret
from tasks.models import PartCostRecalcQueue
from tasks.services.costing import recompute_part_cost_snapshot

logger = logging.getLogger(__name__)


class DrainCostQueueView(APIView):
    """
    Internal endpoint for processing the part cost recalculation queue.
    Called by background workers to drain queued cost calculations.

    POST /tasks/internal/drain-part-cost-queue/
    Headers: X-Queue-Secret: <secret>
    Body: {"max": 200}  # optional, default 200

    Response: {"processed": 5, "failed": 0}

    A bounded batch is fetched once and each part is processed at most once per
    request, in its own transaction. A part whose recompute raises is logged and
    left in the queue for the next run, so one bad part can neither wedge the
    queue (it no longer aborts the whole run) nor spin the CPU.
    """
    authentication_classes = []
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get("max", 200))

        part_ids = list(
            PartCostRecalcQueue.objects
            .order_by("enqueued_at")
            .values_list("part_id", flat=True)[:max_rows]
        )

        processed = 0
        failed = 0
        for part_id in part_ids:
            try:
                with transaction.atomic():
                    locked = (
                        PartCostRecalcQueue.objects
                        .select_for_update(skip_locked=True)
                        .filter(pk=part_id)
                        .first()
                    )
                    if locked is None:
                        # Row is gone or held by another worker — skip it.
                        continue
                    recompute_part_cost_snapshot(part_id)
                    PartCostRecalcQueue.objects.filter(pk=part_id).delete()
                processed += 1
            except Exception:
                logger.exception(
                    "part cost recompute failed for part_id=%s; left in queue",
                    part_id,
                )
                failed += 1

        return Response({"processed": processed, "failed": failed})
