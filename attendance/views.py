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
    compute_overtime_minutes,
    compute_shift_compliance,
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
        overtime = compute_overtime_minutes(request.user, record.check_in_time, now)
        late_minutes, early_leave_minutes = compute_shift_compliance(request.user, record.check_in_time, now)

        record.check_out_time = now
        record.overtime_minutes = overtime
        record.late_minutes = late_minutes
        record.early_leave_minutes = early_leave_minutes
        record.status = AttendanceRecord.STATUS_COMPLETE
        record.save(update_fields=[
            'check_out_time', 'overtime_minutes', 'late_minutes',
            'early_leave_minutes', 'status', 'updated_at',
        ])

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
        # For leave records the serializer already sets status=leave and method=hr_manual.
        # For normal attendance records, default to complete + hr_manual.
        leave_type = serializer.validated_data.get('leave_type')
        if leave_type:
            serializer.save()
        else:
            serializer.save(
                method=AttendanceRecord.METHOD_HR,
                status=AttendanceRecord.STATUS_COMPLETE,
            )


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

            late_minutes, early_leave_minutes = compute_shift_compliance(record.user, record.check_in_time, checkout_time)
            record.check_out_time = checkout_time
            record.overtime_minutes = compute_overtime_minutes(record.user, record.check_in_time, checkout_time)
            record.late_minutes = late_minutes
            record.early_leave_minutes = early_leave_minutes
            record.status = AttendanceRecord.STATUS_COMPLETE
            update_fields += ['check_out_time', 'overtime_minutes', 'late_minutes', 'early_leave_minutes']

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
# Monthly summary
# ---------------------------------------------------------------------------

class MonthlySummaryView(APIView):
    """
    Returns a full day-by-day breakdown of a user's attendance for a given month.
    Includes weekends, public holidays, and absent days.

    GET /attendance/monthly-summary/?user_id=5&year=2026&month=4
    HR can query any user. Employees can only query themselves.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from calendar import monthrange
        from datetime import date, timedelta
        from django.contrib.auth import get_user_model
        from .models import PublicHoliday
        from users.permissions import user_has_role_perm

        User = get_user_model()

        # --- Parse params ---
        try:
            year = int(request.query_params.get('year', timezone.localdate().year))
            month = int(request.query_params.get('month', timezone.localdate().month))
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid year or month.'}, status=status.HTTP_400_BAD_REQUEST)

        if not (1 <= month <= 12):
            return Response({'detail': 'Month must be between 1 and 12.'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = request.query_params.get('user_id')
        is_hr = request.user.is_staff or request.user.is_superuser or user_has_role_perm(request.user, 'manage_hr')

        if user_id and int(user_id) != request.user.id and not is_hr:
            return Response({'detail': 'You can only view your own attendance.'}, status=status.HTTP_403_FORBIDDEN)

        target_user_id = int(user_id) if user_id else request.user.id
        try:
            target_user = User.objects.select_related('profile').get(pk=target_user_id)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        # --- Build date range ---
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        # --- Fetch data ---
        records = {
            r.date: r for r in AttendanceRecord.objects.filter(
                user=target_user, date__gte=first_day, date__lte=last_day
            ).select_related('reviewed_by')
        }
        holidays = {
            h.date: h for h in PublicHoliday.objects.filter(
                date__gte=first_day, date__lte=last_day
            )
        }

        # --- Build day-by-day response ---
        days = []
        current = first_day
        total_working_days = 0
        total_present = 0
        total_absent = 0
        total_overtime_minutes = 0
        total_late_minutes = 0
        total_early_leave_minutes = 0

        while current <= last_day:
            is_weekend = current.weekday() >= 5  # Saturday=5, Sunday=6
            holiday = holidays.get(current)
            record = records.get(current)

            if holiday:
                day_type = 'public_holiday'
            elif is_weekend:
                day_type = 'weekend'
            elif record and record.status == AttendanceRecord.STATUS_LEAVE:
                day_type = 'leave'
            else:
                day_type = 'working'

            if day_type == 'working':
                total_working_days += 1
                if record and record.status in (AttendanceRecord.STATUS_ACTIVE, AttendanceRecord.STATUS_COMPLETE):
                    total_present += 1
                elif record and record.status == AttendanceRecord.STATUS_PENDING:
                    total_present += 1
                elif not record or record.status == AttendanceRecord.STATUS_REJECTED:
                    if current < timezone.localdate():
                        total_absent += 1

            day_data = {
                'date': current.isoformat(),
                'day_type': day_type,
                'weekday': current.strftime('%A'),
                'holiday_name': holiday.local_name if holiday else None,
            }

            if record:
                day_data['record'] = AttendanceRecordSerializer(record).data
                if record.overtime_minutes:
                    total_overtime_minutes += record.overtime_minutes
                if record.late_minutes:
                    total_late_minutes += record.late_minutes
                if record.early_leave_minutes:
                    total_early_leave_minutes += record.early_leave_minutes
            else:
                day_data['record'] = None

            # Flag — only for past working days
            if day_type == 'working' and current < timezone.localdate():
                if not record or record.status == AttendanceRecord.STATUS_REJECTED:
                    day_data['flag'] = 'absent'
                elif record.status == AttendanceRecord.STATUS_PENDING:
                    day_data['flag'] = 'pending_approval'
                elif record.status == AttendanceRecord.STATUS_PENDING_CHECKOUT:
                    day_data['flag'] = 'pending_checkout_approval'
                else:
                    day_data['flag'] = None
            else:
                day_data['flag'] = None

            days.append(day_data)
            current += timedelta(days=1)

        from .services import _get_shift_rule
        rule = _get_shift_rule(target_user)

        return Response({
            'user_id': target_user.id,
            'user_display': target_user.get_full_name() or target_user.username,
            'year': year,
            'month': month,
            'shift_rule': {
                'id': rule.id,
                'name': rule.name,
                'expected_start': rule.expected_start.strftime('%H:%M'),
                'expected_end': rule.expected_end.strftime('%H:%M'),
                'overtime_threshold_minutes': rule.overtime_threshold_minutes,
            } if rule else None,
            'summary': {
                'total_working_days': total_working_days,
                'total_present': total_present,
                'total_absent': total_absent,
                'total_overtime_minutes': total_overtime_minutes,
                'total_late_minutes': total_late_minutes,
                'total_early_leave_minutes': total_early_leave_minutes,
            },
            'days': days,
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
