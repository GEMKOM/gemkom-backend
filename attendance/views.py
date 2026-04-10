from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics

from .models import AttendanceRecord, AttendanceSite, ShiftRule
from .permissions import IsHROrAdmin
from .serializers import (
    AttendanceRecordSerializer,
    CheckInSerializer,
    CheckOutSerializer,
    HRAttendanceCreateSerializer,
    HRAttendanceRecordSerializer,
    AttendanceSiteSerializer,
    ShiftRuleSerializer,
)
from .services import (
    attempt_ip_checkin,
    compute_overtime_hours,
    create_checkin_record,
    get_client_ip,
)


# ---------------------------------------------------------------------------
# Employee self-service
# ---------------------------------------------------------------------------

class CheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = CheckInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        override_reason = ser.validated_data.get('override_reason', '').strip()
        user = request.user

        # Prevent duplicate check-in for today
        today = timezone.localdate()
        if AttendanceRecord.objects.filter(user=user, date=today).exists():
            return Response(
                {'detail': 'You already have an attendance record for today.'},
                status=status.HTTP_409_CONFLICT,
            )

        # --- IP check (white collar path) ---
        if not override_reason:
            success, reason = attempt_ip_checkin(request, user)
            if success:
                try:
                    record = create_checkin_record(
                        user=user,
                        method=AttendanceRecord.METHOD_IP,
                        client_ip=get_client_ip(request),
                    )
                except IntegrityError:
                    return Response(
                        {'detail': 'You already have an attendance record for today.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(
                    AttendanceRecordSerializer(record).data,
                    status=status.HTTP_201_CREATED,
                )

            # IP check failed — tell client why so frontend can offer override
            return Response(
                {'detail': 'Check-in failed.', 'reason': reason},
                status=status.HTTP_403_FORBIDDEN,
            )

        # --- Manual override path ---
        try:
            record = create_checkin_record(
                user=user,
                method=AttendanceRecord.METHOD_OVERRIDE,
                client_ip=get_client_ip(request),
                override_reason=override_reason,
            )
        except IntegrityError:
            return Response(
                {'detail': 'You already have an attendance record for today.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Notify HR — fire-and-forget in a thread to avoid slowing the response
        _notify_hr_override(record)

        return Response(
            AttendanceRecordSerializer(record).data,
            status=status.HTTP_201_CREATED,
        )


class CheckOutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = CheckOutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        today = timezone.localdate()
        try:
            record = AttendanceRecord.objects.get(
                user=request.user,
                date=today,
                status=AttendanceRecord.STATUS_ACTIVE,
            )
        except AttendanceRecord.DoesNotExist:
            return Response(
                {'detail': 'No active check-in found for today.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        now = timezone.now()
        overtime = compute_overtime_hours(request.user, record.check_in_time, now)

        record.check_out_time = now
        record.overtime_hours = overtime
        record.status = AttendanceRecord.STATUS_COMPLETE
        record.save(update_fields=['check_out_time', 'overtime_hours', 'status', 'updated_at'])

        return Response(AttendanceRecordSerializer(record).data)


class TodayRecordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        try:
            record = AttendanceRecord.objects.get(user=request.user, date=today)
        except AttendanceRecord.DoesNotExist:
            return Response({'detail': 'No record for today.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AttendanceRecordSerializer(record).data)


class AttendanceHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        return (
            AttendanceRecord.objects
            .filter(user=self.request.user)
            .order_by('-date')
        )


# ---------------------------------------------------------------------------
# HR views
# ---------------------------------------------------------------------------

class HRRecordListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsHROrAdmin]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return HRAttendanceCreateSerializer
        return HRAttendanceRecordSerializer

    def get_queryset(self):
        qs = AttendanceRecord.objects.select_related('user', 'reviewed_by').order_by('-date', '-check_in_time')

        # Optional query params: ?date=2025-01-20 &user_id=5 &status=pending_override
        date_param = self.request.query_params.get('date')
        user_id = self.request.query_params.get('user_id')
        status_param = self.request.query_params.get('status')

        if date_param:
            qs = qs.filter(date=date_param)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if status_param:
            qs = qs.filter(status=status_param)

        return qs

    def perform_create(self, serializer):
        from .services import compute_overtime_hours
        obj = serializer.save(
            method=AttendanceRecord.METHOD_HR,
            status=AttendanceRecord.STATUS_COMPLETE,
        )
        # Compute overtime if both times are present
        if obj.check_out_time:
            obj.overtime_hours = compute_overtime_hours(obj.user, obj.check_in_time, obj.check_out_time)
            obj.save(update_fields=['overtime_hours'])


class HRRecordDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsHROrAdmin]
    serializer_class = HRAttendanceRecordSerializer
    queryset = AttendanceRecord.objects.select_related('user', 'reviewed_by')


class HRApproveOverrideView(APIView):
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        try:
            record = AttendanceRecord.objects.get(pk=pk, status=AttendanceRecord.STATUS_PENDING)
        except AttendanceRecord.DoesNotExist:
            return Response(
                {'detail': 'Record not found or not in pending_override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        record.status = AttendanceRecord.STATUS_ACTIVE
        record.reviewed_by = request.user
        record.reviewed_at = timezone.now()
        record.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        return Response(HRAttendanceRecordSerializer(record).data)


class HRRejectOverrideView(APIView):
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        try:
            record = AttendanceRecord.objects.get(pk=pk, status=AttendanceRecord.STATUS_PENDING)
        except AttendanceRecord.DoesNotExist:
            return Response(
                {'detail': 'Record not found or not in pending_override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        record.status = AttendanceRecord.STATUS_REJECTED
        record.reviewed_by = request.user
        record.reviewed_at = timezone.now()
        notes = (request.data or {}).get('notes', '')
        if notes:
            record.notes = notes
        record.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'notes', 'updated_at'])

        return Response(HRAttendanceRecordSerializer(record).data)


class HRPendingOverridesView(generics.ListAPIView):
    permission_classes = [IsHROrAdmin]
    serializer_class = HRAttendanceRecordSerializer

    def get_queryset(self):
        return (
            AttendanceRecord.objects
            .filter(status=AttendanceRecord.STATUS_PENDING)
            .select_related('user', 'reviewed_by')
            .order_by('check_in_time')
        )


# ---------------------------------------------------------------------------
# Site config & shift rules (HR)
# ---------------------------------------------------------------------------

class AttendanceSiteView(APIView):
    permission_classes = [IsHROrAdmin]

    def get(self, request):
        site = AttendanceSite.objects.first()
        if site is None:
            return Response({'detail': 'No site configured yet.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(AttendanceSiteSerializer(site).data)

    def put(self, request):
        site = AttendanceSite.objects.first()
        if site is None:
            ser = AttendanceSiteSerializer(data=request.data)
        else:
            ser = AttendanceSiteSerializer(site, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


class ShiftRuleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsHROrAdmin]
    serializer_class = ShiftRuleSerializer
    queryset = ShiftRule.objects.all()


class ShiftRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsHROrAdmin]
    serializer_class = ShiftRuleSerializer
    queryset = ShiftRule.objects.all()


# ---------------------------------------------------------------------------
# Debug (only in DEBUG mode)
# ---------------------------------------------------------------------------

class DebugIPView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not settings.DEBUG:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        return Response({
            'REMOTE_ADDR': request.META.get('REMOTE_ADDR'),
            'HTTP_X_FORWARDED_FOR': request.META.get('HTTP_X_FORWARDED_FOR'),
            'resolved_ip': get_client_ip(request),
        })


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _notify_hr_override(record: AttendanceRecord):
    """
    Fire-and-forget: send an in-app notification to all HR users about
    a pending manual override request.
    """
    import threading

    def _send():
        try:
            from django.contrib.auth import get_user_model
            from notifications.service import bulk_notify, render_notification
            from notifications.models import Notification

            User = get_user_model()

            # HR = staff users or users with manage_hr permission
            hr_users = list(
                User.objects.filter(is_active=True)
                .filter(is_staff=True)
            )
            # Also include users with manage_hr via group/override (best-effort)
            try:
                from users.permissions import user_has_role_perm
                all_users = User.objects.filter(is_active=True, is_staff=False)
                for u in all_users:
                    if user_has_role_perm(u, 'manage_hr') and u not in hr_users:
                        hr_users.append(u)
            except Exception:
                pass

            if not hr_users:
                return

            user_display = record.user.get_full_name() or record.user.username
            title = f"Devam Kaydı: Manuel Onay Gerekiyor — {user_display}"
            body = (
                f"{user_display} bugün ({record.date}) için manuel devam onayı talep etti.\n"
                f"Neden: {record.override_reason or '—'}"
            )
            link = f"/attendance/hr/pending-overrides/"

            for u in hr_users:
                try:
                    from notifications.models import Notification as N
                    N.objects.create(
                        recipient=u,
                        notification_type='attendance_override_requested',
                        title=title,
                        body=body,
                        link=link,
                    )
                except Exception:
                    pass

        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "attendance: failed to send HR override notification: %s", exc
            )

    threading.Thread(target=_send, daemon=True).start()
