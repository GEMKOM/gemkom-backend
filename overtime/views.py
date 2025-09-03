# overtime/views.py
from django.db.models import Q, Prefetch
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend

from .models import OvertimeRequest, OvertimeEntry
from .serializers import (
    OvertimeRequestListSerializer,
    OvertimeRequestDetailSerializer,
    OvertimeRequestCreateSerializer,
    OvertimeRequestUpdateSerializer,
)
from .filters import OvertimeRequestFilter
from .permissions import IsRequesterOrAdmin


# overtime/views.py (add/replace inside your file)
from django.db.models import Q, Prefetch, F
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.contenttypes.models import ContentType

from approvals.models import ApprovalWorkflow, ApprovalStageInstance
from .models import OvertimeRequest, OvertimeEntry
from .serializers import (
    OvertimeRequestListSerializer,
    OvertimeRequestDetailSerializer,
    OvertimeRequestCreateSerializer,
    OvertimeRequestUpdateSerializer,
)
from .filters import OvertimeRequestFilter
from .permissions import IsRequesterOrAdmin
from .approval_service import decide as ot_decide  # approve/reject helper



class OvertimeRequestViewSet(viewsets.ModelViewSet):
    """
    Endpoints:
      - GET  /overtime/requests/                   (list)
      - POST /overtime/requests/                   (create)
      - GET  /overtime/requests/{id}/              (detail)
      - PATCH/PUT /overtime/requests/{id}/         (update reason while submitted)
      - POST /overtime/requests/{id}/cancel/       (cancel if submitted)
      - POST /overtime/requests/{id}/approve/      (approve current stage — approvers only)
      - POST /overtime/requests/{id}/reject/       (reject  current stage — approvers only)
      - GET  /overtime/requests/pending-approvals/ (your approval inbox)
    """
    permission_classes = [IsAuthenticated & IsRequesterOrAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = OvertimeRequestFilter
    ordering = ["-created_at"]
    ordering_fields = ["start_at", "end_at", "status", "created_at"]
    search_fields = ["reason", "entries__job_no", "entries__description"]

    # --- Allow approvers (non-requesters) to hit approve/reject/inbox
    def get_permissions(self):
        # These actions: only need to be logged in (approvers who aren’t requesters)
        if self.action in ["approve", "reject", "pending_approvals"]:
            return [IsAuthenticated()]
        # Everything else: must be authenticated AND requester/admin
        return [IsAuthenticated(), IsRequesterOrAdmin()]

    def get_queryset(self):
        user = self.request.user
        qs = (OvertimeRequest.objects
              .select_related("requester")
              .prefetch_related(
                  Prefetch("entries", queryset=OvertimeEntry.objects.select_related("user"))
              ))
        if getattr(user, "is_admin", False) or getattr(user, "is_superuser", False):
            return qs.distinct()
        # Non-admin: requester or included as entry user
        return qs.filter(Q(requester=user) | Q(entries__user=user)).distinct()

    def get_serializer_class(self):
        if self.action == "create":
            return OvertimeRequestCreateSerializer
        elif self.action in ["update", "partial_update"]:
            return OvertimeRequestUpdateSerializer
        elif self.action == "list":
            return OvertimeRequestListSerializer
        return OvertimeRequestDetailSerializer

    def perform_create(self, serializer):
        obj = serializer.save()
        # serializer already calls send_for_approval(); keep here if you moved it.

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        obj: OvertimeRequest = self.get_object()
        if obj.status != "submitted":
            return Response({"detail": "Only 'submitted' requests can be cancelled."}, status=400)
        obj.status = "cancelled"
        obj.save(update_fields=["status", "updated_at"])
        return Response({"detail": "Request cancelled."}, status=200)

    # ---------- Approvals: Approve / Reject (detail actions) ----------

    def _get_current_stage_for_user(self, ot: OvertimeRequest, user):
        """Fetch current stage and verify `user` is among approvers."""
        ct = ContentType.objects.get_for_model(OvertimeRequest)
        try:
            wf = ApprovalWorkflow.objects.get(content_type=ct, object_id=ot.id)
        except ApprovalWorkflow.DoesNotExist:
            return None, None, "no_workflow"

        stage = (ApprovalStageInstance.objects
                 .filter(workflow=wf,
                         order=wf.current_stage_order,
                         is_complete=False,
                         is_rejected=False)
                 .first())
        if not stage:
            return wf, None, "no_open_stage"

        approver_ids = stage.approver_user_ids or []
        if user.id in approver_ids or getattr(user, "is_superuser", False) or getattr(user, "is_admin", False):
            return wf, stage, "ok"
        return wf, stage, "forbidden"

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        ot: OvertimeRequest = self.get_object()
        wf, stage, state = self._get_current_stage_for_user(ot, request.user)
        if state == "no_workflow":
            return Response({"detail": "No approval workflow found."}, status=404)
        if state == "no_open_stage":
            return Response({"detail": "No pending stage to approve."}, status=400)
        if state == "forbidden":
            return Response({"detail": "You are not an approver for the current stage."}, status=403)

        comment = (request.data or {}).get("comment", "")
        wf = ot_decide(ot, request.user, approve=True, comment=comment)
        return Response({"detail": "Approved.", "status": ot.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        ot: OvertimeRequest = self.get_object()
        wf, stage, state = self._get_current_stage_for_user(ot, request.user)
        if state == "no_workflow":
            return Response({"detail": "No approval workflow found."}, status=404)
        if state == "no_open_stage":
            return Response({"detail": "No pending stage to reject."}, status=400)
        if state == "forbidden":
            return Response({"detail": "You are not an approver for the current stage."}, status=403)

        comment = (request.data or {}).get("comment", "")
        wf = ot_decide(ot, request.user, approve=False, comment=comment)
        return Response({"detail": "Rejected.", "status": ot.status})

    # ---------- Inbox: pending approvals for the current user ----------
    @action(detail=False, methods=["get"], url_path="pending-approvals")
    def pending_approvals(self, request):
        """
        Returns OvertimeRequests where the caller is in the CURRENT stage approvers.
        """
        user = request.user
        ct = ContentType.objects.get_for_model(OvertimeRequest)
        stages = (ApprovalStageInstance.objects
                  .filter(
                      workflow__content_type=ct,
                      workflow__is_complete=False,
                      workflow__is_rejected=False,
                      workflow__current_stage_order=F("order"),
                      is_complete=False,
                      is_rejected=False,
                      approver_user_ids__contains=[user.id],   # Postgres JSONB containment
                  )
                  .select_related("workflow")
                  .order_by("-id"))

        ot_ids = [s.workflow.object_id for s in stages]
        # keep list ordering by stages (optional)
        qs = (OvertimeRequest.objects
              .filter(id__in=ot_ids)
              .select_related("requester")
              .prefetch_related("entries"))

        # Map stage meta (name/order) onto each OT in the response
        stage_map = {s.workflow.object_id: {"order": s.order, "name": s.name} for s in stages}

        data = []
        for ot in qs:
            st = stage_map.get(ot.id, {"order": None, "name": None})
            data.append({
                "id": ot.id,
                "status": ot.status,
                "start_at": ot.start_at,
                "end_at": ot.end_at,
                "duration_hours": ot.duration_hours,
                "team": ot.team,
                "reason": ot.reason,
                "requester": getattr(ot.requester, "username", None),
                "current_stage_order": st["order"],
                "current_stage_name": st["name"],
                "url": f"/overtime/requests/{ot.id}/",  # frontend can link to detail
            })
        return Response(data, status=200)
