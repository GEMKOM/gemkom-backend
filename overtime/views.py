# overtime/views.py
from django.db.models import Q, Prefetch
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth.models import User
from rest_framework.views import APIView
from datetime import date, datetime, time, timedelta
from django.utils import timezone

from .models import OvertimeRequest, OvertimeEntry
from .serializers import (
    OvertimeRequestListSerializer,
    OvertimeRequestDetailSerializer,
    OvertimeRequestCreateSerializer,
    OvertimeRequestUpdateSerializer,
    UserOvertimeListSerializer,
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

from approvals.models import ApprovalDecision, ApprovalWorkflow, ApprovalStageInstance
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
from approvals.services import get_workflow

from django.db.models import Exists, OuterRef, Subquery
from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions



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
        elif self.action in ["list", "pending_approval", "approved_by_me"]:
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

        # set request status
        obj.status = "cancelled"
        obj.save(update_fields=["status", "updated_at"])

        # ALSO mark the approval workflow as cancelled
        try:
            wf = get_workflow(obj)  # generic ctype lookup
        except ApprovalWorkflow.DoesNotExist:
            wf = None
        if wf and not (wf.is_complete or wf.is_rejected or wf.is_cancelled):
            wf.is_cancelled = True
            wf.save(update_fields=["is_cancelled"])

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
    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated], url_path="pending_approval")
    def pending_approval(self, request):
        user = request.user
        ct = ContentType.objects.get_for_model(OvertimeRequest)

        # open CURRENT stages where I’m an approver
        stages_qs = (
            ApprovalStageInstance.objects
            .filter(
                workflow__content_type=ct,
                workflow__is_complete=False,
                workflow__is_rejected=False,
                workflow__is_cancelled=False,          # avoid cancelled workflows
                order=F("workflow__current_stage_order"),
                is_complete=False,
                is_rejected=False,
                approver_user_ids__contains=[user.id], # Postgres JSONB
            )
            .values_list("workflow__object_id", flat=True)
        )

        queryset = (
            OvertimeRequest.objects
            .filter(id__in=Subquery(stages_qs), status="submitted")  # only submitted OTs
            .select_related("requester")
            .prefetch_related(Prefetch("entries", queryset=OvertimeEntry.objects.select_related("user")))
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(queryset)
        ser = self.get_serializer(page if page is not None else queryset, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)
    
    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated], url_path="decision_by_me")
    def decision_by_me(self, request):
        user = request.user
        decision_type = request.query_params.get("decision", "")
        since = request.query_params.get("since")
        until = request.query_params.get("until")

        ct_ot = ContentType.objects.get_for_model(OvertimeRequest)

        my_decisions = ApprovalDecision.objects.filter(
            stage_instance__workflow__content_type=ct_ot,
            stage_instance__workflow__object_id=OuterRef("pk"),
            approver=user,
        )
        if decision_type in ("approve", "reject"):
            my_decisions = my_decisions.filter(decision=decision_type)
        if since:
            my_decisions = my_decisions.filter(decided_at__gte=since)
        if until:
            my_decisions = my_decisions.filter(decided_at__lt=until)

        queryset = (
            OvertimeRequest.objects
            .annotate(i_decided=Exists(my_decisions))
            .filter(i_decided=True)
            .select_related("requester")
            .prefetch_related(Prefetch("entries", queryset=OvertimeEntry.objects.select_related("user")))
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(queryset)
        ser = self.get_serializer(page if page is not None else queryset, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


class OvertimeUsersForDateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def _from_iso_or_dot(s: str) -> date | None:
        s = (s or "").strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def get(self, request, date_str=None, yyyy=None, mm=None, dd=None):
        # Accept either /.../<YYYY-MM-DD>/  OR  /.../<YYYY>/<MM>/<DD>/
        if yyyy and mm and dd:
            try:
                day = date(int(yyyy), int(mm), int(dd))
            except ValueError:
                day = None
        else:
            day = self._from_iso_or_dot(date_str)

        if not day:
            return Response(
                {"detail": "Invalid date. Use /.../YYYY-MM-DD/ or /.../YYYY/MM/DD/ (e.g., 2025-09-12)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tz = timezone.get_current_timezone()
        start_of_day = timezone.make_aware(datetime.combine(day, time.min), tz)
        end_of_day = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), tz)

        user_ids = (
            OvertimeEntry.objects
            .filter(
                request__status="approved",
                request__start_at__lte=end_of_day,
                request__end_at__gte=start_of_day,
            )
            .values_list("user_id", flat=True)
            .distinct()
        )

        day_entries_qs = (
            OvertimeEntry.objects
            .filter(
                request__status="approved",
                request__start_at__lt=end_of_day,
                request__end_at__gte=start_of_day,
            )
            .only("id", "job_no", "description", "approved_hours", "user_id", "request_id", "request__start_at","request__end_at")
            .select_related(None)  # ensure we don't drag extra relations
        )

        users = (User.objects
                 .filter(id__in=user_ids, is_active=True)
                 .select_related("profile")
                 .order_by("first_name", "last_name", "username"))

        serializer = UserOvertimeListSerializer(
            users, many=True,
            context={"start_of_day": start_of_day, "end_exclusive": end_of_day}
        )
        data = serializer.data
        return Response(data, status=status.HTTP_200_OK)