from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from machining.permissions import HasQueueSecret
from subcontracting.models import SubcontractorCostRecalcQueue
from subcontracting.services.costing import recompute_subcontractor_cost


class DrainSubcontractorCostQueueView(APIView):
    """
    Internal endpoint for processing the subcontractor cost recalculation queue.
    Called by background workers (Cloud Run scheduler).

    POST /subcontracting/internal/drain-cost-queue/
    Headers: X-Queue-Secret: <secret>
    Body: {"max": 200}  (optional, default 200)
    Response: {"processed": N}
    """
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get('max', 200))
        processed = 0

        while processed < max_rows:
            with transaction.atomic():
                rows = list(
                    SubcontractorCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by('enqueued_at')[:max_rows - processed]
                )
                if not rows:
                    break

            for r in rows:
                try:
                    recompute_subcontractor_cost(r.job_no)
                finally:
                    SubcontractorCostRecalcQueue.objects.filter(job_no=r.job_no).delete()
                processed += 1

        return Response({'processed': processed})
