from rest_framework.views import APIView
from rest_framework.response import Response
from django.db import transaction

from machining.permissions import HasQueueSecret
from tasks.models import PartCostRecalcQueue
from tasks.services.costing import recompute_part_cost_snapshot


class DrainCostQueueView(APIView):
    """
    Internal endpoint for processing the part cost recalculation queue.
    Called by background workers to drain queued cost calculations.

    POST /tasks/internal/drain-part-cost-queue/
    Headers: X-Queue-Secret: <secret>
    Body: {"max": 200}  # optional, default 200

    Response: {"processed": 5}
    """
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get("max", 200))
        processed = 0

        while processed < max_rows:
            with transaction.atomic():
                rows = list(
                    PartCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by("enqueued_at")[:max_rows - processed]
                )
                if not rows:
                    break

            # Process outside the transaction to avoid long locks
            for r in rows:
                recompute_part_cost_snapshot(r.part_id)
                PartCostRecalcQueue.objects.filter(part_id=r.part_id).delete()
                processed += 1

        return Response({"processed": processed})
