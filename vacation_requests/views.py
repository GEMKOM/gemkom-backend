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
from machining.permissions import HasQueueSecret
from users.permissions import user_has_role_perm

from .approval_service import decide as vr_decide
from .filters import VacationRequestFilter
from .models import LEAVE_TYPE_CHOICES, UserLeaveBalance, VacationRequest
from .serializers import (
    UserLeaveBalanceSerializer,
    UserLeaveSetupSerializer,
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

        if self.request.query_params.get("mine") == "true":
            return qs.filter(requester=user).distinct()

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
            return qs

        return qs.filter(user=user)

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

        holiday_map = {
            h.date: h
            for h in PublicHoliday.objects.filter(date__gte=start, date__lte=end)
        }

        from decimal import Decimal
        excluded = []
        working_days = Decimal("0")
        current = start
        while current <= end:
            holiday = holiday_map.get(current)
            if current.weekday() >= 5:
                excluded.append({"date": current.isoformat(), "reason": "weekend"})
            elif holiday and not holiday.is_half_day:
                excluded.append({"date": current.isoformat(), "reason": "public_holiday", "name": holiday.local_name})
            elif holiday and holiday.is_half_day:
                working_days += Decimal("0.5")
                excluded.append({"date": current.isoformat(), "reason": "half_day_holiday", "name": holiday.local_name})
            else:
                working_days += Decimal("1")
            current += timedelta(days=1)

        return Response({
            "start_date":    start_str,
            "end_date":      end_str,
            "duration_days": working_days,
            "excluded":      excluded,
        })


# ---------------------------------------------------------------------------
# Internal scheduler endpoint — credit annual leave on work anniversaries
# ---------------------------------------------------------------------------

class CreditAnnualLeaveView(APIView):
    """
    POST /vacation-requests/internal/credit-annual-leave/
    Headers: X-Queue-Secret: <secret>

    Called daily by Cloud Scheduler. Credits annual leave entitlement to users
    whose work anniversary falls on the date provided (or today if omitted).
    Body (optional): {"date": "YYYY-MM-DD"}
    """
    authentication_classes = []
    permission_classes     = [HasQueueSecret]

    def post(self, request):
        from decimal import Decimal

        from django.contrib.auth import get_user_model
        from django.db import transaction as db_transaction

        from core.emails import send_plain_email
        from vacation_requests.management.commands.credit_annual_leave import (
            _entitled_days,
            _is_anniversary_today,
        )

        User = get_user_model()

        date_str = (request.data or {}).get("date")
        if date_str:
            try:
                today = date.fromisoformat(date_str)
            except ValueError:
                return Response({"detail": "Invalid date format, use YYYY-MM-DD."}, status=400)
        else:
            today = date.today()

        users = (
            User.objects
            .filter(is_active=True, profile__hire_date__isnull=False)
            .select_related("profile")
        )

        credited = []
        skipped  = []

        for user in users:
            hire_date = user.profile.hire_date
            if not _is_anniversary_today(hire_date, today):
                continue

            balance = UserLeaveBalance.objects.filter(user=user).first()
            if balance and balance.last_credited_date == today:
                skipped.append(user.get_full_name() or user.username)
                continue

            birth_date = getattr(user.profile, "birth_date", None)
            days = _entitled_days(hire_date, today, birth_date)
            if days == 0:
                continue

            with db_transaction.atomic():
                balance, _ = UserLeaveBalance.objects.get_or_create(
                    user=user,
                    defaults={"total_days": Decimal("0"), "used_days": Decimal("0")},
                )
                balance.total_days += Decimal(str(days))
                balance.last_credited_date = today
                balance.save(update_fields=["total_days", "last_credited_date"])

            completed_years = (
                today.year - hire_date.year
                - (1 if (today.month, today.day) < (hire_date.month, hire_date.day) else 0)
            )
            credited.append({
                "user":            user.get_full_name() or user.username,
                "username":        user.username,
                "days_added":      days,
                "completed_years": completed_years,
                "new_total":       str(balance.total_days),
            })

        # Send email to HR regardless — even on days with no activity
        self._notify_hr(today, credited, skipped)

        return Response({
            "date":       today.isoformat(),
            "credited":   credited,
            "already_done": skipped,
        })

    @staticmethod
    def _notify_hr(today, credited, skipped):
        from django.contrib.auth import get_user_model
        from core.emails import send_plain_email

        User = get_user_model()
        hr_emails = list(
            User.objects
            .filter(is_active=True, groups__name="hr_team")
            .exclude(email="")
            .values_list("email", flat=True)
            .distinct()
        )
        if not hr_emails:
            return

        lines = [
            f"Yıllık İzin Kredi Raporu — {today.strftime('%d %B %Y')}",
            "=" * 50,
            "",
        ]

        if credited:
            lines.append(f"Bugün İzin Kredisi Eklenen Çalışanlar ({len(credited)}):")
            lines.append("-" * 40)
            for entry in credited:
                lines.append(
                    f"  • {entry['user']} (@{entry['username']})"
                    f"  |  +{entry['days_added']} gün"
                    f"  |  {entry['completed_years']}. yıl dönümü"
                    f"  |  Yeni toplam: {entry['new_total']} gün"
                )
        else:
            lines.append("Bugün yıl dönümü olan çalışan bulunmamaktadır.")

        if skipped:
            lines.append("")
            lines.append(f"Daha Önce İşlenmiş (atlandı) ({len(skipped)}):")
            for name in skipped:
                lines.append(f"  • {name}")

        lines += [
            "",
            "=" * 50,
            "Bu e-posta otomatik olarak GemCore sistemi tarafından gönderilmiştir.",
        ]

        send_plain_email(
            subject=f"[GemCore] Yıllık İzin Kredi Raporu — {today.strftime('%d.%m.%Y')}",
            body="\n".join(lines),
            to=hr_emails,
        )


# ---------------------------------------------------------------------------
# Upcoming leaves — who is on leave and when
# ---------------------------------------------------------------------------

class UpcomingLeavesView(APIView):
    """
    GET /vacation-requests/upcoming-leaves/

    Returns all approved vacation requests overlapping the next 30 days.
    Sorted by start_date. One row per request — designed for a table view.

    Query params:
      from_date  YYYY-MM-DD  (default: today)
      to_date    YYYY-MM-DD  (default: today + 30 days)
      team       filter by team (e.g. "welding")
      user_id    filter to a single user
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from users.helpers import TEAM_LABELS

        today = date.today()

        try:
            from_date = date.fromisoformat(request.query_params["from_date"]) if "from_date" in request.query_params else today
            to_date   = date.fromisoformat(request.query_params["to_date"])   if "to_date"   in request.query_params else today + timedelta(days=30)
        except ValueError:
            return Response({"detail": "Dates must be YYYY-MM-DD."}, status=400)

        if to_date < from_date:
            return Response({"detail": "to_date must be on or after from_date."}, status=400)

        qs = (
            VacationRequest.objects
            .filter(
                status=VacationRequest.STATUS_APPROVED,
                start_date__lte=to_date,
                end_date__gte=from_date,
            )
            .select_related("requester")
            .order_by("start_date", "requester__first_name", "requester__last_name")
        )

        if team := request.query_params.get("team"):
            qs = qs.filter(team=team)
        if user_id := request.query_params.get("user_id"):
            qs = qs.filter(requester_id=user_id)

        leave_type_map = dict(LEAVE_TYPE_CHOICES)

        results = [
            {
                "id":               vr.pk,
                "user_id":          vr.requester_id,
                "full_name":        vr.requester.get_full_name() or vr.requester.username,
                "team":             vr.team,
                "team_label":       TEAM_LABELS.get(vr.team, vr.team or ""),
                "leave_type":       vr.leave_type,
                "leave_type_label": leave_type_map.get(vr.leave_type, vr.leave_type),
                "start_date":       vr.start_date.isoformat(),
                "end_date":         vr.end_date.isoformat(),
                "duration_days":    str(vr.duration_days),
            }
            for vr in qs
        ]

        return Response({
            "from_date": from_date.isoformat(),
            "to_date":   to_date.isoformat(),
            "count":     len(results),
            "results":   results,
        })


# ---------------------------------------------------------------------------
# HR leave setup — hire_date + total_days in one endpoint per user
# ---------------------------------------------------------------------------

class UserLeaveSetupView(APIView):
    """
    GET  /vacation-requests/users/{user_id}/leave-setup/  → current hire_date + balance
    PATCH /vacation-requests/users/{user_id}/leave-setup/ → update hire_date and/or total_days

    HR-only (manage_hr permission, staff, or superuser).
    """
    permission_classes = [IsAuthenticated]

    def _check_hr(self, request):
        if not (
            request.user.is_staff
            or request.user.is_superuser
            or user_has_role_perm(request.user, "manage_hr")
        ):
            return Response({"detail": "Bu işlem için HR yetkisi gereklidir."}, status=403)
        return None

    def _get_user_or_404(self, user_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        try:
            return User.objects.select_related("profile", "leave_balance").get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None

    def _build_response(self, user):
        from decimal import Decimal
        profile = getattr(user, "profile", None)
        balance = getattr(user, "leave_balance", None)
        used_days      = balance.used_days      if balance else Decimal("0")
        total_days     = balance.total_days     if balance else Decimal("0")
        remaining_days = total_days - used_days
        return {
            "user_id":        user.pk,
            "username":       user.username,
            "full_name":      user.get_full_name() or user.username,
            "hire_date":      profile.hire_date.isoformat()  if (profile and profile.hire_date)  else None,
            "birth_date":     profile.birth_date.isoformat() if (profile and profile.birth_date) else None,
            "total_days":     str(total_days),
            "used_days":      str(used_days),
            "remaining_days": str(remaining_days),
        }

    def get(self, request, user_id):
        err = self._check_hr(request)
        if err:
            return err
        user = self._get_user_or_404(user_id)
        if not user:
            return Response({"detail": "Kullanıcı bulunamadı."}, status=404)
        return Response(self._build_response(user))

    def patch(self, request, user_id):
        from decimal import Decimal
        from django.db import transaction as db_transaction

        err = self._check_hr(request)
        if err:
            return err
        user = self._get_user_or_404(user_id)
        if not user:
            return Response({"detail": "Kullanıcı bulunamadı."}, status=404)

        ser = UserLeaveSetupSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with db_transaction.atomic():
            profile = getattr(user, "profile", None)
            if profile:
                profile_fields = []
                if "hire_date" in data:
                    profile.hire_date = data["hire_date"]
                    profile_fields.append("hire_date")
                if "birth_date" in data:
                    profile.birth_date = data["birth_date"]
                    profile_fields.append("birth_date")
                if profile_fields:
                    profile.save(update_fields=profile_fields)

            if "total_days" in data:
                from .models import LeaveBalanceLog
                balance, _ = UserLeaveBalance.objects.get_or_create(
                    user=user,
                    defaults={"total_days": Decimal("0"), "used_days": Decimal("0")},
                )
                old_total = balance.total_days
                balance.total_days = data["total_days"]
                balance.save(update_fields=["total_days"])
                delta = balance.total_days - old_total
                LeaveBalanceLog.objects.create(
                    user=user,
                    kind=LeaveBalanceLog.KIND_HR_ADJUSTMENT,
                    delta=delta,
                    balance_after=balance.remaining_days,
                    created_by=request.user,
                    note=f"HR düzeltmesi: {old_total} → {balance.total_days} gün",
                )

        # Re-fetch to get fresh values
        user = self._get_user_or_404(user_id)
        return Response(self._build_response(user))


# ---------------------------------------------------------------------------
# Leave balance ledger
# ---------------------------------------------------------------------------

class LeaveBalanceLedgerView(APIView):
    """
    GET /vacation-requests/users/{user_id}/leave-ledger/

    HR-only. Returns a chronological ledger of every event that affected
    a user's annual leave balance, with a running balance after each entry.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        from .models import LeaveBalanceLog

        if not (request.user.is_staff or request.user.is_superuser or user_has_role_perm(request.user, "manage_hr")):
            return Response({"detail": "Bu işlem için yetkiniz yok."}, status=403)

        from django.contrib.auth import get_user_model
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return Response({"detail": "Kullanıcı bulunamadı."}, status=404)

        logs = LeaveBalanceLog.objects.filter(user=user).select_related(
            "vacation_request", "created_by"
        ).order_by("created_at")

        entries = []
        for log in logs:
            entry = {
                "id":           log.pk,
                "date":         log.created_at.date().isoformat(),
                "kind":         log.kind,
                "kind_label":   log.get_kind_display(),
                "delta":        str(log.delta),
                "balance_after": str(log.balance_after),
                "note":         log.note,
                "created_by":   log.created_by.get_full_name() or log.created_by.username if log.created_by else None,
            }
            if log.vacation_request_id:
                vr = log.vacation_request
                entry["request"] = {
                    "id":         vr.pk,
                    "leave_type": vr.leave_type,
                    "start_date": vr.start_date.isoformat(),
                    "end_date":   vr.end_date.isoformat(),
                }
            else:
                entry["request"] = None
            entries.append(entry)

        try:
            balance = UserLeaveBalance.objects.get(user=user)
            current = {
                "total_days":     str(balance.total_days),
                "used_days":      str(balance.used_days),
                "remaining_days": str(balance.remaining_days),
            }
        except UserLeaveBalance.DoesNotExist:
            current = {"total_days": "0", "used_days": "0", "remaining_days": "0"}

        return Response({
            "user_id":  user.pk,
            "username": user.username,
            "current_balance": current,
            "entries":  entries,
        })


# ---------------------------------------------------------------------------
# My leave summary
# ---------------------------------------------------------------------------

class MyLeaveSummaryView(APIView):
    """
    GET /vacation-requests/my-summary/

    Returns the authenticated user's full leave picture:
      - Annual leave balance (total / used / remaining)
      - Request counts by status (submitted / approved / rejected / cancelled)
      - Days used per leave type (approved requests only)
      - Upcoming approved leave (next entry)
      - Hire date and years of service
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from decimal import Decimal
        from django.db.models import Count, Sum

        user = request.user
        today = date.today()

        # ── Annual leave balance ──────────────────────────────────────────
        try:
            balance = UserLeaveBalance.objects.get(user=user)
            total_days     = balance.total_days
            used_days      = balance.used_days
            remaining_days = balance.remaining_days
            last_credited  = balance.last_credited_date
        except UserLeaveBalance.DoesNotExist:
            total_days = used_days = remaining_days = Decimal("0")
            last_credited = None

        # ── Request counts by status ──────────────────────────────────────
        counts = (
            VacationRequest.objects
            .filter(requester=user)
            .values("status")
            .annotate(n=Count("id"))
        )
        status_counts = {row["status"]: row["n"] for row in counts}

        # ── Days used per leave type (approved only) ──────────────────────
        leave_type_label_map = dict(LEAVE_TYPE_CHOICES)
        approved_by_type = (
            VacationRequest.objects
            .filter(requester=user, status=VacationRequest.STATUS_APPROVED)
            .values("leave_type")
            .annotate(days=Sum("duration_days"), count=Count("id"))
            .order_by("leave_type")
        )
        by_type = [
            {
                "leave_type":        row["leave_type"],
                "leave_type_label":  leave_type_label_map.get(row["leave_type"], row["leave_type"]),
                "approved_requests": row["count"],
                "days_used":         str(row["days"] or Decimal("0")),
            }
            for row in approved_by_type
        ]

        # ── Upcoming approved leave ───────────────────────────────────────
        next_leave = (
            VacationRequest.objects
            .filter(requester=user, status=VacationRequest.STATUS_APPROVED, end_date__gte=today)
            .order_by("start_date")
            .first()
        )
        upcoming = None
        if next_leave:
            upcoming = {
                "id":               next_leave.pk,
                "leave_type_label": leave_type_label_map.get(next_leave.leave_type, next_leave.leave_type),
                "start_date":       next_leave.start_date.isoformat(),
                "end_date":         next_leave.end_date.isoformat(),
                "duration_days":    str(next_leave.duration_days),
            }

        # ── Hire date & service years ─────────────────────────────────────
        hire_date = None
        years_of_service = None
        profile = getattr(user, "profile", None)
        if profile and getattr(profile, "hire_date", None):
            hire_date = profile.hire_date
            years_of_service = (
                today.year - hire_date.year
                - (1 if (today.month, today.day) < (hire_date.month, hire_date.day) else 0)
            )

        return Response({
            "annual_leave": {
                "total_days":     str(total_days),
                "used_days":      str(used_days),
                "remaining_days": str(remaining_days),
                "last_credited":  last_credited.isoformat() if last_credited else None,
            },
            "requests": {
                "total":     sum(status_counts.values()),
                "submitted": status_counts.get(VacationRequest.STATUS_SUBMITTED, 0),
                "approved":  status_counts.get(VacationRequest.STATUS_APPROVED, 0),
                "rejected":  status_counts.get(VacationRequest.STATUS_REJECTED, 0),
                "cancelled": status_counts.get(VacationRequest.STATUS_CANCELLED, 0),
            },
            "by_leave_type": by_type,
            "upcoming_leave": upcoming,
            "hire_date":        hire_date.isoformat() if hire_date else None,
            "years_of_service": years_of_service,
        })
