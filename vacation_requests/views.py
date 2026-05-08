from __future__ import annotations

from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, F, OuterRef, Q, Subquery
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from approvals.models import ApprovalDecision, ApprovalStageInstance, ApprovalWorkflow
from approvals.services import get_workflow
from users.permissions import user_has_role_perm

from .approval_service import decide as vr_decide
from .filters import VacationRequestFilter
from .models import LEAVE_TYPE_CHOICES, UserLeaveBalance, VacationRequest
from .serializers import (
    UserLeaveBalanceSerializer,
    VacationRequestCreateSerializer,
    VacationRequestDetailSerializer,
    VacationRequestListSerializer,
    VacationRequestUpdateSerializer,
)


class VacationRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class    = VacationRequestFilter
    ordering           = ["-created_at"]
    ordering_fields    = ["start_date", "end_date", "status", "created_at", "duration_days"]
    search_fields      = ["reason", "requester__username", "requester__first_name", "requester__last_name"]

    def get_queryset(self):
        user = self.request.user
        qs = VacationRequest.objects.select_related("requester").prefetch_related("approvals")

        if user.is_staff or user.is_superuser or user_has_role_perm(user, "office_access"):
            return qs.distinct()

        ct = ContentType.objects.get_for_model(VacationRequest)
        approver_ids = (
            ApprovalStageInstance.objects
            .filter(workflow__content_type=ct, approver_user_ids__contains=[user.id])
            .values_list("workflow__object_id", flat=True)
        )
        return qs.filter(Q(requester=user) | Q(id__in=approver_ids)).distinct()

    def get_serializer_class(self):
        if self.action == "create":
            return VacationRequestCreateSerializer
        if self.action in ["update", "partial_update"]:
            return VacationRequestUpdateSerializer
        if self.action in ["list", "pending_approval", "decision_by_me"]:
            return VacationRequestListSerializer
        return VacationRequestDetailSerializer

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        vr: VacationRequest = self.get_object()
        if vr.requester_id != request.user.id and not (request.user.is_staff or request.user.is_superuser):
            return Response({"detail": "Yalnızca talebi oluşturan kişi iptal edebilir."}, status=403)
        if vr.status not in (VacationRequest.STATUS_SUBMITTED, VacationRequest.STATUS_APPROVED):
            return Response({"detail": "Yalnızca onay bekleyen veya onaylanmış talepler iptal edilebilir."}, status=400)

        was_approved = vr.status == VacationRequest.STATUS_APPROVED
        vr.status = VacationRequest.STATUS_CANCELLED
        vr.save(update_fields=["status", "updated_at"])

        try:
            wf = get_workflow(vr)
        except ApprovalWorkflow.DoesNotExist:
            wf = None
        if wf and not (wf.is_complete or wf.is_rejected or wf.is_cancelled):
            wf.is_cancelled = True
            wf.save(update_fields=["is_cancelled"])

        if was_approved:
            vr._rollback_attendance_records()
            vr._refund_leave_balance()

        return Response({"detail": "Talep iptal edildi."}, status=200)

    # ------------------------------------------------------------------
    # Approve / Reject
    # ------------------------------------------------------------------

    def _get_current_stage_for_user(self, vr: VacationRequest, user):
        ct = ContentType.objects.get_for_model(VacationRequest)
        try:
            wf = ApprovalWorkflow.objects.get(content_type=ct, object_id=vr.id)
        except ApprovalWorkflow.DoesNotExist:
            return None, None, "no_workflow"

        stage = (
            ApprovalStageInstance.objects
            .filter(workflow=wf, order=wf.current_stage_order, is_complete=False, is_rejected=False)
            .first()
        )
        if not stage:
            return wf, None, "no_open_stage"

        approver_ids = stage.approver_user_ids or []
        if user.id in approver_ids or user.is_superuser or user.is_staff:
            return wf, stage, "ok"
        return wf, stage, "forbidden"

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        vr: VacationRequest = self.get_object()
        wf, stage, state = self._get_current_stage_for_user(vr, request.user)
        if state == "no_workflow":
            return Response({"detail": "Onay akışı bulunamadı."}, status=404)
        if state == "no_open_stage":
            return Response({"detail": "Onaylanacak aşama bulunamadı."}, status=400)
        if state == "forbidden":
            return Response({"detail": "Bu aşama için onay yetkiniz bulunmuyor."}, status=403)

        comment = (request.data or {}).get("comment", "")
        vr_decide(vr, request.user, approve=True, comment=comment)
        return Response({"detail": "Onaylandı.", "status": vr.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        vr: VacationRequest = self.get_object()
        wf, stage, state = self._get_current_stage_for_user(vr, request.user)
        if state == "no_workflow":
            return Response({"detail": "Onay akışı bulunamadı."}, status=404)
        if state == "no_open_stage":
            return Response({"detail": "Reddedilecek aşama bulunamadı."}, status=400)
        if state == "forbidden":
            return Response({"detail": "Bu aşama için red yetkiniz bulunmuyor."}, status=403)

        comment = (request.data or {}).get("comment", "")
        vr_decide(vr, request.user, approve=False, comment=comment)
        return Response({"detail": "Reddedildi.", "status": vr.status})

    # ------------------------------------------------------------------
    # Approval inbox
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="pending_approval")
    def pending_approval(self, request):
        user = request.user
        ct   = ContentType.objects.get_for_model(VacationRequest)

        stages_qs = (
            ApprovalStageInstance.objects
            .filter(
                workflow__content_type=ct,
                workflow__is_complete=False,
                workflow__is_rejected=False,
                workflow__is_cancelled=False,
                order=F("workflow__current_stage_order"),
                is_complete=False,
                is_rejected=False,
                approver_user_ids__contains=[user.id],
            )
            .values_list("workflow__object_id", flat=True)
        )

        queryset = (
            VacationRequest.objects
            .filter(id__in=Subquery(stages_qs), status=VacationRequest.STATUS_SUBMITTED)
            .select_related("requester")
            .prefetch_related("approvals")
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(queryset)
        ser  = self.get_serializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)

    @action(detail=False, methods=["get"], url_path="decision_by_me")
    def decision_by_me(self, request):
        user          = request.user
        decision_type = request.query_params.get("decision", "")
        since         = request.query_params.get("since")
        until         = request.query_params.get("until")

        ct = ContentType.objects.get_for_model(VacationRequest)
        my_decisions = ApprovalDecision.objects.filter(
            stage_instance__workflow__content_type=ct,
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
            VacationRequest.objects
            .annotate(i_decided=Exists(my_decisions))
            .filter(i_decided=True)
            .select_related("requester")
            .prefetch_related("approvals")
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(queryset)
        ser  = self.get_serializer(
            page if page is not None else queryset,
            many=True,
            context=self.get_serializer_context(),
        )
        return self.get_paginated_response(ser.data) if page is not None else Response(ser.data)


# ---------------------------------------------------------------------------
# Leave balance viewset
# ---------------------------------------------------------------------------

class UserLeaveBalanceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class   = UserLeaveBalanceSerializer
    http_method_names  = ["get", "patch", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs   = UserLeaveBalance.objects.select_related("user")

        if user.is_staff or user.is_superuser or user_has_role_perm(user, "manage_hr"):
            target_user = self.request.query_params.get("user_id")
            if target_user:
                qs = qs.filter(user_id=target_user)
            year = self.request.query_params.get("year")
            if year:
                qs = qs.filter(year=year)
            return qs

        year = self.request.query_params.get("year")
        qs   = qs.filter(user=user)
        if year:
            qs = qs.filter(year=year)
        return qs

    def partial_update(self, request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser or user_has_role_perm(request.user, "manage_hr")):
            return Response({"detail": "İzin bakiyesi düzenleme yetkiniz yok."}, status=403)
        return super().partial_update(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------

class VacationPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from attendance.models import PublicHoliday

        start_str = request.query_params.get("start_date")
        end_str   = request.query_params.get("end_date")

        if not start_str or not end_str:
            return Response({"detail": "start_date and end_date are required."}, status=400)

        try:
            start = date.fromisoformat(start_str)
            end   = date.fromisoformat(end_str)
        except ValueError:
            return Response({"detail": "Dates must be in YYYY-MM-DD format."}, status=400)

        if end < start:
            return Response({"detail": "end_date must be on or after start_date."}, status=400)

        holidays = {
            h.date: h.local_name
            for h in PublicHoliday.objects.filter(date__gte=start, date__lte=end)
        }

        excluded = []
        working_days = 0
        current = start
        while current <= end:
            if current.weekday() >= 5:
                excluded.append({"date": current.isoformat(), "reason": "weekend"})
            elif current in holidays:
                excluded.append({"date": current.isoformat(), "reason": "public_holiday", "name": holidays[current]})
            else:
                working_days += 1
            current += timedelta(days=1)

        return Response({
            "start_date":    start_str,
            "end_date":      end_str,
            "duration_days": working_days,
            "excluded":      excluded,
        })
