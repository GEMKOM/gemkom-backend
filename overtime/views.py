# overtime/views.py
from django.db.models import Prefetch
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from rest_framework.views import APIView
from datetime import date, datetime, time, timedelta
from django.utils import timezone

from approvals.models import ApprovalWorkflow, ApprovalStageInstance
from .models import OvertimeRequest, OvertimeEntry
from .serializers import (
    OvertimeRequestListSerializer,
    OvertimeRequestDetailSerializer,
    OvertimeRequestCreateSerializer,
    OvertimeRequestUpdateSerializer,
    UserOvertimeListSerializer,
)
from .filters import OvertimeRequestFilter



# overtime/views.py (add/replace inside your file)
from django.db.models import Prefetch
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

from .approval_service import decide as ot_decide  # approve/reject helper
from .approval_service import reject_entries as ot_reject_entries  # post-approval retraction
from approvals.services import get_workflow

from django.db.models import Exists, OuterRef, Subquery, F, Q
from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions

from users.permissions import user_has_role_perm
from .services.cost import compute_request_cost_impact
from .services.cost_report import build_overtime_cost_report
from .services.report import build_machining_overtime_report



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
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = OvertimeRequestFilter
    ordering = ["-created_at"]
    ordering_fields = ["start_at", "end_at", "status", "created_at"]
    search_fields = ["reason", "entries__job_no", "entries__description"]

    def get_queryset(self):
        user = self.request.user
        qs = (OvertimeRequest.objects
              .select_related("requester")
              .prefetch_related(
                  Prefetch("entries", queryset=OvertimeEntry.objects.select_related("user"))
              ))
        from users.permissions import user_has_role_perm
        if user.is_staff or user.is_superuser or user_has_role_perm(user, 'office_access'):
            return qs.distinct()

        # Workshop users: only their own requests / entries
        ct = ContentType.objects.get_for_model(OvertimeRequest)
        approver_ids = (ApprovalStageInstance.objects
                        .filter(workflow__content_type=ct,
                                approver_user_ids__contains=[user.id])
                        .values_list("workflow__object_id", flat=True))
        return qs.filter(
            Q(requester=user) | Q(entries__user=user) | Q(id__in=approver_ids)
        ).distinct()

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
        if user.id in approver_ids or user.is_superuser or user.is_staff:
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

        # ---- Partial approval: reject a subset of operator entries ----
        rejected_entry_ids = (request.data or {}).get("rejected_entry_ids", []) or []
        if rejected_entry_ids:
            valid_ids = set(
                ot.entries.filter(id__in=rejected_entry_ids).values_list("id", flat=True)
            )
            invalid = set(rejected_entry_ids) - valid_ids
            if invalid:
                return Response(
                    {"detail": f"Bu talebe ait olmayan kalem(ler): {sorted(invalid)}"},
                    status=400,
                )
            # Only entries that are still open (pending) may be rejected here.
            ot.entries.filter(id__in=valid_ids, status="pending").update(
                status="rejected",
                decided_by=request.user,
                decided_at=timezone.now(),
            )

        wf = ot_decide(ot, request.user, approve=True, comment=comment)
        ot.refresh_from_db()
        return Response({"detail": "Approved.", "status": ot.status})

    @action(detail=True, methods=["get"], url_path="cost_impact")
    def cost_impact(self, request, pk=None):
        """
        Per-job current vs projected profit and total overtime cost.
        Restricted to users with cost visibility (`view_job_costs`).
        """
        if not user_has_role_perm(request.user, "view_job_costs"):
            return Response(
                {"detail": "Maliyet görüntüleme yetkiniz yok."}, status=403
            )
        ot: OvertimeRequest = self.get_object()
        return Response(compute_request_cost_impact(ot))

    def _is_workflow_approver(self, ot: OvertimeRequest, user) -> bool:
        """True if `user` is (or was) an approver on any stage of this request."""
        if user.is_superuser or user.is_staff:
            return True
        ct = ContentType.objects.get_for_model(OvertimeRequest)
        approver_lists = (ApprovalStageInstance.objects
                          .filter(workflow__content_type=ct, workflow__object_id=ot.id)
                          .values_list("approver_user_ids", flat=True))
        return any(user.id in (ids or []) for ids in approver_lists)

    @action(detail=True, methods=["post"], url_path="reject_entries")
    def reject_entries(self, request, pk=None):
        """
        Reject individual participant entries — including on an already-approved
        request (an approver retracting people). Body: {entry_ids: [int], comment}.
        Only workflow approvers (any stage) or staff may do this.
        """
        ot: OvertimeRequest = self.get_object()
        if ot.status not in ("approved", "submitted"):
            return Response(
                {"detail": "Sadece onaylı veya bekleyen taleplerde kişi reddedilebilir."},
                status=400,
            )
        if not self._is_workflow_approver(ot, request.user):
            return Response({"detail": "Bu talep için onaylayıcı değilsiniz."}, status=403)

        data = request.data or {}
        entry_ids = data.get("entry_ids") or data.get("rejected_entry_ids") or []
        if not entry_ids:
            return Response({"detail": "Reddedilecek kişi seçilmedi."}, status=400)

        valid_ids = set(ot.entries.filter(id__in=entry_ids).values_list("id", flat=True))
        invalid = set(entry_ids) - valid_ids
        if invalid:
            return Response(
                {"detail": f"Bu talebe ait olmayan kalem(ler): {sorted(invalid)}"},
                status=400,
            )

        comment = data.get("comment", "")
        ot, updated = ot_reject_entries(ot, request.user, list(valid_ids), comment=comment)
        ot.refresh_from_db()
        return Response({
            "detail": "Seçili kişiler reddedildi.",
            "status": ot.status,
            "rejected_count": updated,
        })

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

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated], url_path="cost_report")
    def cost_report(self, request):
        """
        Total overtime cost over a period, broken down by team / person / job,
        with a per-request drill-down (each request carries its entries).

        Query params:
          start_date, end_date  YYYY-MM-DD (default: current month to date)
          status                repeatable or comma-separated (default: approved)
          team, user, job_no    optional filters

        Restricted to users with cost visibility (`view_job_costs`), same gate
        as the per-request `cost_impact` action.
        """
        if not user_has_role_perm(request.user, "view_job_costs"):
            return Response({"detail": "Maliyet görüntüleme yetkiniz yok."}, status=403)

        params = request.query_params
        raw_statuses = params.getlist("status") or []
        statuses = [s.strip() for chunk in raw_statuses for s in chunk.split(",") if s.strip()]

        try:
            data = build_overtime_cost_report(
                start_date=params.get("start_date") or None,
                end_date=params.get("end_date") or None,
                statuses=statuses or None,
                team=params.get("team") or None,
                user_id=params.get("user") or None,
                job_no=params.get("job_no") or None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated], url_path="machining_operators")
    def machining_operators(self, request):
        """
        Active users who work machining operations — i.e. hold the
        `access_machining_tasks` permission (resolved through Django
        groups/positions). Used by the create form to decide which overtime
        entries should offer the machining-operation multi-select, and by the
        machining report's operator filter.
        """
        qs = (User.objects
              .with_perm("users.access_machining_tasks")
              .filter(is_active=True)
              .order_by("first_name", "last_name", "username"))
        data = [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.get_full_name() or u.username,
            }
            for u in qs
        ]
        return Response(data)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated], url_path="machining_report")
    def machining_report(self, request):
        """
        Report of approved overtime requests that carry machining operations,
        showing whether each operation was worked that day and for how long.
        Query params: start_date, end_date (YYYY-MM-DD), user, job_no.
        """
        params = request.query_params
        rows = build_machining_overtime_report(
            start_date=params.get("start_date") or None,
            end_date=params.get("end_date") or None,
            user_id=params.get("user") or None,
            job_no=params.get("job_no") or None,
        )
        return Response(rows)


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

        # Exclude entries rejected during partial approval. Use exclude(rejected)
        # rather than filter(approved): pre-existing entries carry the default
        # status='pending' and must still be shown.
        user_ids = (
            OvertimeEntry.objects
            .filter(
                request__status="approved",
                request__start_at__lte=end_of_day,
                request__end_at__gte=start_of_day,
            )
            .exclude(status="rejected")
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
            .exclude(status="rejected")
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