from django.conf import settings
from django.db import IntegrityError, models
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
    UserShiftRuleAssignSerializer,
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

        checkout_override_reason = ser.validated_data.get('override_reason', '').strip()

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

        # --- Checkout override path ---
        if checkout_override_reason:
            record.override_reason = (record.override_reason + ' | Çıkış: ' + checkout_override_reason).strip(' | ')
            record.status = AttendanceRecord.STATUS_PENDING_CHECKOUT
            record.save(update_fields=['override_reason', 'status', 'updated_at'])
            _notify_hr_checkout_override(record)
            return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_200_OK)

        # --- IP verification ---
        success, reason = attempt_ip_checkin(request, request.user)
        if not success:
            return Response(
                {'detail': 'Check-out failed.', 'reason': reason},
                status=status.HTTP_403_FORBIDDEN,
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

        params = self.request.query_params

        # Single date: ?date=2025-01-20
        date_param = params.get('date')
        # Date range: ?date_from=2025-01-01&date_to=2025-01-31
        date_from = params.get('date_from')
        date_to = params.get('date_to')
        # User filters: ?user_id=5 or ?username=john or ?name=john (searches first+last name)
        user_id = params.get('user_id')
        username = params.get('username')
        name = params.get('name')
        # Group filter: ?group_id=3 or ?group_name=Kaynak
        group_id = params.get('group_id')
        group_name = params.get('group_name')

        status_param = params.get('status')
        method_param = params.get('method')

        if date_param:
            qs = qs.filter(date=date_param)
        else:
            if date_from:
                qs = qs.filter(date__gte=date_from)
            if date_to:
                qs = qs.filter(date__lte=date_to)

        if user_id:
            qs = qs.filter(user_id=user_id)
        if username:
            qs = qs.filter(user__username__icontains=username)
        if name:
            qs = qs.filter(
                models.Q(user__first_name__icontains=name) |
                models.Q(user__last_name__icontains=name)
            )

        if group_id:
            qs = qs.filter(user__groups__id=group_id)
        if group_name:
            qs = qs.filter(user__groups__name__icontains=group_name)

        if status_param:
            qs = qs.filter(status=status_param)
        if method_param:
            qs = qs.filter(method=method_param)

        return qs.distinct()

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
    """
    Unified approve endpoint for both check-in and checkout overrides.

    pending_override (check-in):
      - Optional body: {"check_in_time": "..."}  — defaults to the existing check_in_time
      - Sets status → active

    pending_checkout_override (checkout):
      - Optional body: {"check_out_time": "..."}  — defaults to now
      - Sets check_out_time, computes overtime, sets status → complete
    """
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        try:
            record = AttendanceRecord.objects.get(
                pk=pk,
                status__in=[AttendanceRecord.STATUS_PENDING, AttendanceRecord.STATUS_PENDING_CHECKOUT],
            )
        except AttendanceRecord.DoesNotExist:
            return Response(
                {'detail': 'Record not found or not in a pending override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from datetime import datetime
        from zoneinfo import ZoneInfo

        app_tz = ZoneInfo(settings.APP_DEFAULT_TZ)
        now = timezone.now()
        update_fields = ['status', 'reviewed_by', 'reviewed_at', 'updated_at']

        def _parse_time(raw):
            """
            Parse datetime string. If naive (no tz offset), treat as APP_DEFAULT_TZ (Istanbul)
            and convert to UTC-aware. If already tz-aware, keep as-is.
            """
            try:
                dt = datetime.fromisoformat(str(raw))
            except ValueError:
                raise ValueError(f"Invalid datetime format: {raw}")
            if timezone.is_naive(dt):
                dt = dt.replace(tzinfo=app_tz)
            return dt

        if record.status == AttendanceRecord.STATUS_PENDING:
            # Check-in override — optionally correct the check-in time
            time_raw = (request.data or {}).get('check_in_time')
            if time_raw:
                try:
                    record.check_in_time = _parse_time(time_raw)
                    update_fields.append('check_in_time')
                except Exception:
                    return Response({'detail': 'Invalid check_in_time format.'}, status=status.HTTP_400_BAD_REQUEST)
            record.status = AttendanceRecord.STATUS_ACTIVE

        else:
            # Checkout override — optionally set an explicit checkout time
            time_raw = (request.data or {}).get('check_out_time')
            if time_raw:
                try:
                    checkout_time = _parse_time(time_raw)
                except Exception:
                    return Response({'detail': 'Invalid check_out_time format.'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                checkout_time = now

            record.check_out_time = checkout_time
            record.overtime_hours = compute_overtime_hours(record.user, record.check_in_time, checkout_time)
            record.status = AttendanceRecord.STATUS_COMPLETE
            update_fields += ['check_out_time', 'overtime_hours']

        record.reviewed_by = request.user
        record.reviewed_at = now
        record.save(update_fields=update_fields)

        return Response(HRAttendanceRecordSerializer(record).data)


class HRRejectOverrideView(APIView):
    """
    Unified reject endpoint for both check-in and checkout overrides.

    pending_override (check-in):
      - Sets status → override_rejected

    pending_checkout_override (checkout):
      - Reverts status → active (worker is still checked in, HR must resolve manually)

    Optional body: {"notes": "..."}
    """
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        try:
            record = AttendanceRecord.objects.get(
                pk=pk,
                status__in=[AttendanceRecord.STATUS_PENDING, AttendanceRecord.STATUS_PENDING_CHECKOUT],
            )
        except AttendanceRecord.DoesNotExist:
            return Response(
                {'detail': 'Record not found or not in a pending override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if record.status == AttendanceRecord.STATUS_PENDING:
            record.status = AttendanceRecord.STATUS_REJECTED
        else:
            # Checkout rejection — revert to active so worker/HR can resolve
            record.status = AttendanceRecord.STATUS_ACTIVE

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
            .filter(status__in=[
                AttendanceRecord.STATUS_PENDING,
                AttendanceRecord.STATUS_PENDING_CHECKOUT,
            ])
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


class ShiftRuleAssignView(APIView):
    """
    Assign or unassign a shift rule for a user.
    POST /attendance/hr/shift-rules/assign/
    Body: {"user_id": 5, "shift_rule_id": 2}  — assign rule 2 to user 5
    Body: {"user_id": 5, "shift_rule_id": null} — clear assignment, user falls back to default
    """
    permission_classes = [IsHROrAdmin]

    def post(self, request):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        ser = UserShiftRuleAssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        user_id = ser.validated_data['user_id']
        shift_rule_id = ser.validated_data['shift_rule_id']

        try:
            user = User.objects.select_related('profile').get(pk=user_id)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not hasattr(user, 'profile'):
            return Response({'detail': 'User has no profile.'}, status=status.HTTP_400_BAD_REQUEST)

        if shift_rule_id is not None:
            try:
                rule = ShiftRule.objects.get(pk=shift_rule_id, is_active=True)
            except ShiftRule.DoesNotExist:
                return Response({'detail': 'Shift rule not found or inactive.'}, status=status.HTTP_404_NOT_FOUND)
            user.profile.shift_rule = rule
        else:
            user.profile.shift_rule = None

        user.profile.save(update_fields=['shift_rule'])

        return Response({
            'user_id': user.id,
            'user_display': user.get_full_name() or user.username,
            'shift_rule_id': user.profile.shift_rule_id,
            'shift_rule_name': user.profile.shift_rule.name if user.profile.shift_rule else None,
        })


# ---------------------------------------------------------------------------
# Debug (only in DEBUG mode)
# ---------------------------------------------------------------------------

class DebugIPView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (request.user.is_superuser or request.user.is_staff):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        return Response({
            'REMOTE_ADDR': request.META.get('REMOTE_ADDR'),
            'HTTP_X_FORWARDED_FOR': request.META.get('HTTP_X_FORWARDED_FOR'),
            'resolved_ip': get_client_ip(request),
        })


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _notify_hr_checkout_override(record: AttendanceRecord):
    """Notify HR about a pending checkout override request."""
    import threading

    def _send():
        try:
            from django.contrib.auth import get_user_model
            from users.permissions import user_has_role_perm

            User = get_user_model()
            hr_users = list(User.objects.filter(is_active=True, is_staff=True))
            try:
                for u in User.objects.filter(is_active=True, is_staff=False):
                    if user_has_role_perm(u, 'manage_hr') and u not in hr_users:
                        hr_users.append(u)
            except Exception:
                pass

            if not hr_users:
                return

            user_display = record.user.get_full_name() or record.user.username
            title = f"Çıkış Kaydı: Manuel Onay Gerekiyor — {user_display}"
            body = (
                f"{user_display} bugün ({record.date}) için manuel çıkış onayı talep etti.\n"
                f"Neden: {record.override_reason or '—'}"
            )
            link = "/attendance/hr/pending-overrides/"

            for u in hr_users:
                try:
                    from notifications.models import Notification as N
                    N.objects.create(
                        recipient=u,
                        notification_type='attendance_checkout_override_requested',
                        title=title,
                        body=body,
                        link=link,
                    )
                except Exception:
                    pass
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "attendance: failed to send HR checkout override notification: %s", exc
            )

    threading.Thread(target=_send, daemon=True).start()


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
