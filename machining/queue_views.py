from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction

from machining.permissions import HasQueueSecret
from machining.models import JobCostRecalcQueue
from machining.services.costing import recompute_task_cost_snapshot

class DrainCostQueueView(APIView):
    permission_classes = [HasQueueSecret]

    def post(self, request):
        max_rows = int(request.data.get("max", 200))
        processed = 0
        while processed < max_rows:
            with transaction.atomic():
                rows = list(
                    JobCostRecalcQueue.objects
                    .select_for_update(skip_locked=True)
                    .order_by("enqueued_at")[:max_rows - processed]
                )
                if not rows:
                    break
            for r in rows:
                recompute_task_cost_snapshot(r.task_id)
                JobCostRecalcQueue.objects.filter(task_id=r.task_id).delete()
                processed += 1
        return Response({"processed": processed})
