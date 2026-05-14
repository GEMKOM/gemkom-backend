from django.conf import settings
from django.db import models
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import generics

from .models import AttendanceLeaveInterval, AttendanceRecord, AttendanceSession, AttendanceSite, ShiftRule
from .permissions import IsHROrAdmin
from .serializers import (
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CheckInSerializer,
    CheckOutSerializer,
    HRAttendanceCreateSerializer,
    HRAttendanceRecordSerializer,
    HRAttendanceSummarySerializer,
    HRLeaveIntervalCreateSerializer,
    HRSessionSerializer,
    AttendanceSiteSerializer,
    ShiftRuleSerializer,
    UserShiftRuleAssignSerializer,
)
from .services import (
    attempt_ip_checkin,
    create_session,
    get_or_create_record,
    get_client_ip,
    recompute_record_aggregates,
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
        today = timezone.localdate()

        # Reject if a leave record already exists for today
        existing = AttendanceRecord.objects.filter(user=user, date=today).first()
        if existing and existing.status == AttendanceRecord.STATUS_LEAVE:
            return Response(
                {'detail': 'You are marked as on leave today.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Reject if there is already an open session today
        if existing:
            open_session = existing.sessions.filter(
                status__in=[AttendanceSession.STATUS_OPEN, AttendanceSession.STATUS_PENDING]
            ).first()
            if open_session:
                return Response(
                    {'detail': 'You already have an open session today. Check out first.'},
                    status=status.HTTP_409_CONFLICT,
                )

        # --- IP check (standard path) ---
        if not override_reason:
            success, reason = attempt_ip_checkin(request, user)
            if not success:
                return Response(
                    {'detail': 'Check-in failed.', 'reason': reason},
                    status=status.HTTP_403_FORBIDDEN,
                )

            record = get_or_create_record(user, today)
            # Reactivate a completed record (user is returning after a break)
            if record.status in (AttendanceRecord.STATUS_COMPLETE, AttendanceRecord.STATUS_REJECTED):
                record.status = AttendanceRecord.STATUS_ACTIVE
                record.save(update_fields=['status', 'updated_at'])

            session = create_session(
                record=record,
                method=AttendanceSession.METHOD_IP,
                client_ip=get_client_ip(request),
            )
            return Response(
                AttendanceRecordSerializer(record).data,
                status=status.HTTP_201_CREATED,
            )

        # --- Manual override path ---
        record = get_or_create_record(user, today)
        if record.status in (AttendanceRecord.STATUS_COMPLETE, AttendanceRecord.STATUS_REJECTED):
            record.status = AttendanceRecord.STATUS_ACTIVE
            record.save(update_fields=['status', 'updated_at'])

        session = create_session(
            record=record,
            method=AttendanceSession.METHOD_OVERRIDE,
            client_ip=get_client_ip(request),
            override_reason=override_reason,
        )

        # Mark the day record as pending so HR can see it
        record.status = AttendanceRecord.STATUS_PENDING
        record.save(update_fields=['status', 'updated_at'])

        _notify_hr_override(record, session)

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

        # Find the currently open session
        open_session = record.sessions.filter(status=AttendanceSession.STATUS_OPEN).first()
        if open_session is None:
            return Response(
                {'detail': 'No open session found. You are not currently checked in.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # --- Checkout override path ---
        if checkout_override_reason:
            open_session.override_reason = (
                (open_session.override_reason + ' | Çıkış: ' + checkout_override_reason).strip(' | ')
            )
            open_session.status = AttendanceSession.STATUS_PENDING_CHECKOUT
            open_session.save(update_fields=['override_reason', 'status', 'updated_at'])

            record.status = AttendanceRecord.STATUS_PENDING_CHECKOUT
            record.save(update_fields=['status', 'updated_at'])

            _notify_hr_checkout_override(record, open_session)
            return Response(AttendanceRecordSerializer(record).data, status=status.HTTP_200_OK)

        # --- IP verification ---
        success, reason = attempt_ip_checkin(request, request.user)
        if not success:
            return Response(
                {'detail': 'Check-out failed.', 'reason': reason},
                status=status.HTTP_403_FORBIDDEN,
            )

        now = timezone.now()
        open_session.check_out_time = now
        open_session.status = AttendanceSession.STATUS_CLOSED
        open_session.save(update_fields=['check_out_time', 'status', 'updated_at'])

        # Check if any sessions are still open
        has_open = record.sessions.filter(status=AttendanceSession.STATUS_OPEN).exists()
        if not has_open:
            record.status = AttendanceRecord.STATUS_COMPLETE
            record.save(update_fields=['status', 'updated_at'])

        recompute_record_aggregates(record)

        return Response(AttendanceRecordSerializer(record).data)


class TodayRecordView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        record = (
            AttendanceRecord.objects
            .filter(user=request.user, date=today)
            .prefetch_related('sessions', 'leave_intervals')
            .first()
        )
        if record is None:
            return Response(None, status=status.HTTP_200_OK)
        return Response(AttendanceRecordSerializer(record).data)


class AttendanceHistoryView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        return (
            AttendanceRecord.objects
            .filter(user=self.request.user)
            .prefetch_related('sessions', 'leave_intervals')
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
        qs = (
            AttendanceRecord.objects
            .select_related('user', 'reviewed_by')
            .prefetch_related('sessions', 'leave_intervals')
            .order_by('-date')
        )

        params = self.request.query_params

        date_param = params.get('date')
        date_from = params.get('date_from')
        date_to = params.get('date_to')
        user_id = params.get('user_id')
        username = params.get('username')
        name = params.get('name')
        group_id = params.get('group_id')
        group_name = params.get('group_name')
        status_param = params.get('status')

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
            qs = qs.filter(user__profile__position_id=group_id)
        if group_name:
            qs = qs.filter(user__profile__position__department_code__icontains=group_name)

        if status_param:
            qs = qs.filter(status=status_param)

        return qs.distinct()

    def perform_create(self, serializer):
        leave_type = serializer.validated_data.get('leave_type')
        if leave_type:
            serializer.save()
        else:
            serializer.save()


class HRRecordDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsHROrAdmin]
    serializer_class = HRAttendanceRecordSerializer
    queryset = (
        AttendanceRecord.objects
        .select_related('user', 'reviewed_by')
        .prefetch_related('sessions', 'leave_intervals')
    )


class HRAttendanceSummaryView(APIView):
    """
    GET /attendance/hr/summary/

    Returns one row per user covering the queried date range.
    Each row aggregates all AttendanceRecord rows for that user within the range.

    Query params (all optional):
      date_from, date_to  — ISO dates; default to today if omitted
      user_id             — filter to a single user
      username            — icontains filter
      name                — first/last name icontains filter
      group_id            — position pk filter
      group_name          — position department_code icontains filter

    Response fields per user row:
      user_id, user_display,
      date_from, date_to,
      total_working_days        — weekdays minus public holidays in range
      days_present              — days with active/complete/pending record
      days_leave                — days with leave record
      days_absent               — past working days with no record or rejected
      total_present_minutes     — sum of record.total_present_minutes
      total_expected_minutes    — working_days × user's shift length in minutes
      total_overtime_minutes    — sum
      total_late_minutes        — sum
      total_early_leave_minutes — sum
      session_count             — total sessions across all records in range
    """
    permission_classes = [IsHROrAdmin]

    def get(self, request):
        from datetime import date, timedelta
        from django.contrib.auth import get_user_model
        from django.db.models import Count, Sum, Q

        User = get_user_model()
        params = request.query_params
        today = timezone.localdate()

        # --- Date range ---
        try:
            date_from = date.fromisoformat(params['date_from']) if params.get('date_from') else today
            date_to = date.fromisoformat(params['date_to']) if params.get('date_to') else today
        except ValueError:
            return Response({'detail': 'Invalid date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        if date_from > date_to:
            return Response({'detail': 'date_from must be <= date_to.'}, status=status.HTTP_400_BAD_REQUEST)

        # --- Build working-day set for the range (weekdays minus full public holidays) ---
        from .models import PublicHoliday
        holiday_dates = set(
            PublicHoliday.objects.filter(
                date__gte=date_from,
                date__lte=date_to,
                is_half_day=False,
            ).values_list('date', flat=True)
        )
        all_working_days = set()
        cur = date_from
        while cur <= date_to:
            if cur.weekday() < 5 and cur not in holiday_dates:
                all_working_days.add(cur)
            cur += timedelta(days=1)
        total_working_days_in_range = len(all_working_days)

        # --- Filter records ---
        qs = (
            AttendanceRecord.objects
            .filter(date__gte=date_from, date__lte=date_to)
            .select_related('user__profile__shift_rule')
            .prefetch_related('sessions')
        )

        user_id = params.get('user_id')
        username = params.get('username')
        name = params.get('name')
        group_id = params.get('group_id')
        group_name = params.get('group_name')

        if user_id:
            qs = qs.filter(user_id=user_id)
        if username:
            qs = qs.filter(user__username__icontains=username)
        if name:
            qs = qs.filter(
                Q(user__first_name__icontains=name) | Q(user__last_name__icontains=name)
            )
        if group_id:
            qs = qs.filter(user__profile__position_id=group_id)
        if group_name:
            qs = qs.filter(user__profile__position__department_code__icontains=group_name)

        # --- Aggregate per user in Python (avoids complex multi-join SQL) ---
        from collections import defaultdict
        from .services import _get_shift_rule

        user_records = defaultdict(list)
        for rec in qs.distinct():
            user_records[rec.user_id].append(rec)

        # If filtering by user, also ensure users with zero records in range appear
        # (only when user_id is explicitly requested)
        if user_id and not user_records:
            try:
                target_user = User.objects.select_related('profile__shift_rule').get(pk=user_id)
                user_records[target_user.pk] = []
            except User.DoesNotExist:
                return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Pre-fetch users we need
        user_ids = list(user_records.keys())
        users = {
            u.pk: u
            for u in User.objects.select_related('profile__shift_rule').filter(pk__in=user_ids)
        }

        rows = []
        for uid, records in user_records.items():
            user_obj = users.get(uid)
            if not user_obj:
                continue

            rule = _get_shift_rule(user_obj)
            shift_minutes = 0
            if rule:
                from datetime import datetime as _dt
                start_dt = _dt.combine(date_from, rule.expected_start)
                end_dt = _dt.combine(date_from, rule.expected_end)
                shift_minutes = max(0, int((end_dt - start_dt).total_seconds() // 60))

            total_expected_minutes = total_working_days_in_range * shift_minutes

            # Aggregate from records
            total_present_minutes = 0
            total_overtime = 0
            total_late = 0
            total_early_leave = 0
            session_count = 0
            days_present = 0
            days_leave = 0
            days_absent = 0

            # Track which working days are accounted for
            accounted_days = set()

            for rec in records:
                if rec.status == AttendanceRecord.STATUS_LEAVE:
                    days_leave += 1
                    accounted_days.add(rec.date)
                elif rec.status in (
                    AttendanceRecord.STATUS_ACTIVE,
                    AttendanceRecord.STATUS_COMPLETE,
                    AttendanceRecord.STATUS_PENDING,
                    AttendanceRecord.STATUS_PENDING_CHECKOUT,
                ):
                    days_present += 1
                    accounted_days.add(rec.date)
                elif rec.status == AttendanceRecord.STATUS_REJECTED:
                    accounted_days.add(rec.date)  # rejected still counts as attempted

                total_present_minutes += rec.total_present_minutes or 0
                total_overtime += rec.overtime_minutes or 0
                total_late += rec.late_minutes or 0
                total_early_leave += rec.early_leave_minutes or 0
                session_count += rec.sessions.count()

            # Absent = past working days with no record or a rejected record
            for d in all_working_days:
                if d >= today:
                    continue  # don't count today or future as absent
                rec_for_day = next((r for r in records if r.date == d), None)
                if rec_for_day is None or rec_for_day.status == AttendanceRecord.STATUS_REJECTED:
                    days_absent += 1

            rows.append({
                'user_id': uid,
                'user_display': user_obj.get_full_name() or user_obj.username,
                'date_from': date_from,
                'date_to': date_to,
                'total_working_days': total_working_days_in_range,
                'days_present': days_present,
                'days_leave': days_leave,
                'days_absent': days_absent,
                'total_present_minutes': total_present_minutes,
                'total_expected_minutes': total_expected_minutes,
                'total_overtime_minutes': total_overtime,
                'total_late_minutes': total_late,
                'total_early_leave_minutes': total_early_leave,
                'session_count': session_count,
            })

        rows.sort(key=lambda r: r['user_display'])
        ser = HRAttendanceSummarySerializer(rows, many=True)
        return Response(ser.data)


class HRApproveOverrideView(APIView):
    """
    Unified approve endpoint for both check-in and checkout session overrides.

    pending_override (check-in session):
      - Optional body: {"check_in_time": "..."}  — defaults to the session's existing time
      - Session status → open; record status → active

    pending_checkout_override (checkout session):
      - Optional body: {"check_out_time": "..."}  — defaults to now
      - Session status → closed; aggregates recomputed; record status → complete (if no open sessions)
    """
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        # pk refers to the AttendanceSession, not the record
        try:
            session = AttendanceSession.objects.select_related('record__user').get(
                pk=pk,
                status__in=[AttendanceSession.STATUS_PENDING, AttendanceSession.STATUS_PENDING_CHECKOUT],
            )
        except AttendanceSession.DoesNotExist:
            return Response(
                {'detail': 'Session not found or not in a pending override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        from datetime import datetime
        from zoneinfo import ZoneInfo

        app_tz = ZoneInfo(settings.APP_DEFAULT_TZ)
        now = timezone.now()
        record = session.record

        def _parse_time(raw):
            try:
                dt = datetime.fromisoformat(str(raw))
            except ValueError:
                raise ValueError(f"Invalid datetime format: {raw}")
            if timezone.is_naive(dt):
                dt = dt.replace(tzinfo=app_tz)
            return dt

        if session.status == AttendanceSession.STATUS_PENDING:
            # Check-in override approval
            time_raw = (request.data or {}).get('check_in_time')
            if time_raw:
                try:
                    session.check_in_time = _parse_time(time_raw)
                except Exception:
                    return Response({'detail': 'Invalid check_in_time format.'}, status=status.HTTP_400_BAD_REQUEST)
            session.status = AttendanceSession.STATUS_OPEN
            session.save(update_fields=['check_in_time', 'status', 'updated_at'])

            record.status = AttendanceRecord.STATUS_ACTIVE
            record.reviewed_by = request.user
            record.reviewed_at = now
            record.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

        else:
            # Checkout override approval
            time_raw = (request.data or {}).get('check_out_time')
            if time_raw:
                try:
                    checkout_time = _parse_time(time_raw)
                except Exception:
                    return Response({'detail': 'Invalid check_out_time format.'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                checkout_time = now

            session.check_out_time = checkout_time
            session.status = AttendanceSession.STATUS_CLOSED
            session.save(update_fields=['check_out_time', 'status', 'updated_at'])

            has_open = record.sessions.filter(status=AttendanceSession.STATUS_OPEN).exists()
            record.status = AttendanceRecord.STATUS_ACTIVE if has_open else AttendanceRecord.STATUS_COMPLETE
            record.reviewed_by = request.user
            record.reviewed_at = now
            record.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

            recompute_record_aggregates(record)

        return Response(HRAttendanceRecordSerializer(record).data)


class HRRejectOverrideView(APIView):
    """
    Unified reject endpoint for both check-in and checkout session overrides.

    pending_override (check-in):
      - Session status → override_rejected; record status → override_rejected

    pending_checkout_override (checkout):
      - Session status → open (reverts); record status → active

    Optional body: {"notes": "..."}
    """
    permission_classes = [IsHROrAdmin]

    def post(self, request, pk):
        try:
            session = AttendanceSession.objects.select_related('record').get(
                pk=pk,
                status__in=[AttendanceSession.STATUS_PENDING, AttendanceSession.STATUS_PENDING_CHECKOUT],
            )
        except AttendanceSession.DoesNotExist:
            return Response(
                {'detail': 'Session not found or not in a pending override status.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        record = session.record
        now = timezone.now()

        if session.status == AttendanceSession.STATUS_PENDING:
            session.status = AttendanceSession.STATUS_REJECTED
            session.save(update_fields=['status', 'updated_at'])
            # Mark record rejected only if there are no other active/open sessions
            has_open = record.sessions.filter(
                status__in=[AttendanceSession.STATUS_OPEN, AttendanceSession.STATUS_PENDING]
            ).exists()
            if not has_open:
                record.status = AttendanceRecord.STATUS_REJECTED
        else:
            # Revert checkout session to open — worker still checked in
            session.status = AttendanceSession.STATUS_OPEN
            session.save(update_fields=['status', 'updated_at'])
            record.status = AttendanceRecord.STATUS_ACTIVE

        record.reviewed_by = request.user
        record.reviewed_at = now
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
            .prefetch_related('sessions', 'leave_intervals')
            .order_by('date')
        )


# ---------------------------------------------------------------------------
# HR — session management
# ---------------------------------------------------------------------------

class HRSessionListCreateView(generics.ListCreateAPIView):
    """
    GET  /attendance/hr/records/{record_id}/sessions/  — list sessions for a record
    POST /attendance/hr/records/{record_id}/sessions/  — manually add a session
    """
    permission_classes = [IsHROrAdmin]
    serializer_class = HRSessionSerializer

    def _get_record(self):
        try:
            return AttendanceRecord.objects.get(pk=self.kwargs['record_id'])
        except AttendanceRecord.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Attendance record not found.')

    def get_queryset(self):
        return AttendanceSession.objects.filter(record_id=self.kwargs['record_id'])

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['record'] = self._get_record()
        return ctx

    def perform_create(self, serializer):
        record = self.get_serializer_context()['record']
        session = serializer.save(record=record, method=AttendanceSession.METHOD_HR)
        if session.check_out_time:
            session.status = AttendanceSession.STATUS_CLOSED
            session.save(update_fields=['status', 'updated_at'])
            recompute_record_aggregates(record)
            if record.status not in (AttendanceRecord.STATUS_LEAVE,):
                record.status = AttendanceRecord.STATUS_COMPLETE
                record.save(update_fields=['status', 'updated_at'])


class HRSessionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /attendance/hr/sessions/{id}/
    """
    permission_classes = [IsHROrAdmin]
    serializer_class = HRSessionSerializer
    queryset = AttendanceSession.objects.select_related('record__user')

    def perform_update(self, serializer):
        session = serializer.save()
        recompute_record_aggregates(session.record)

    def perform_destroy(self, instance):
        record = instance.record
        instance.delete()
        recompute_record_aggregates(record)


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
    Body: {"user_id": 5, "shift_rule_id": 2}   — assign rule 2 to user 5
    Body: {"user_id": 5, "shift_rule_id": null} — clear assignment
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

        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        records = {
            r.date: r for r in AttendanceRecord.objects.filter(
                user=target_user, date__gte=first_day, date__lte=last_day
            ).prefetch_related('sessions', 'leave_intervals').select_related('reviewed_by')
        }
        holidays = {
            h.date: h for h in PublicHoliday.objects.filter(
                date__gte=first_day, date__lte=last_day
            )
        }

        days = []
        current = first_day
        total_working_days = 0
        total_present = 0
        total_absent = 0
        total_overtime_minutes = 0
        total_late_minutes = 0
        total_early_leave_minutes = 0
        total_present_minutes = 0

        while current <= last_day:
            is_weekend = current.weekday() >= 5
            holiday = holidays.get(current)
            record = records.get(current)

            if holiday and not holiday.is_half_day:
                day_type = 'public_holiday'
            elif is_weekend:
                day_type = 'weekend'
            elif record and record.status == AttendanceRecord.STATUS_LEAVE:
                day_type = 'leave'
            else:
                day_type = 'working'

            if day_type == 'working':
                total_working_days += 1
                if record and record.status in (
                    AttendanceRecord.STATUS_ACTIVE,
                    AttendanceRecord.STATUS_COMPLETE,
                    AttendanceRecord.STATUS_PENDING,
                ):
                    total_present += 1
                elif not record or record.status == AttendanceRecord.STATUS_REJECTED:
                    if current < timezone.localdate():
                        total_absent += 1

            day_data = {
                'date': current.isoformat(),
                'day_type': day_type,
                'weekday': current.strftime('%A'),
                'holiday_name': holiday.local_name if holiday else None,
                'is_half_day_holiday': holiday.is_half_day if holiday else False,
            }

            if record:
                day_data['record'] = AttendanceRecordSerializer(record).data
                total_overtime_minutes += record.overtime_minutes
                total_late_minutes += record.late_minutes
                total_early_leave_minutes += record.early_leave_minutes
                total_present_minutes += record.total_present_minutes
            else:
                day_data['record'] = None

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
                'total_present_minutes': total_present_minutes,
                'total_overtime_minutes': total_overtime_minutes,
                'total_late_minutes': total_late_minutes,
                'total_early_leave_minutes': total_early_leave_minutes,
            },
            'days': days,
        })


# ---------------------------------------------------------------------------
# Leave intervals (HR)
# ---------------------------------------------------------------------------

class HRLeaveIntervalListCreateView(generics.ListCreateAPIView):
    """
    GET  /attendance/hr/records/{record_id}/intervals/
    POST /attendance/hr/records/{record_id}/intervals/
    """
    permission_classes = [IsHROrAdmin]
    serializer_class = HRLeaveIntervalCreateSerializer

    def _get_record(self):
        try:
            return AttendanceRecord.objects.get(pk=self.kwargs['record_id'])
        except AttendanceRecord.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('Attendance record not found.')

    def get_queryset(self):
        return AttendanceLeaveInterval.objects.filter(record_id=self.kwargs['record_id'])

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['record'] = self._get_record()
        return ctx

    def perform_create(self, serializer):
        record = self.get_serializer_context()['record']
        interval = serializer.save(record=record)
        recompute_record_aggregates(interval.record)


class HRLeaveIntervalDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /attendance/hr/intervals/{id}/"""
    permission_classes = [IsHROrAdmin]
    serializer_class = HRLeaveIntervalCreateSerializer
    queryset = AttendanceLeaveInterval.objects.select_related('record__user')

    def perform_update(self, serializer):
        interval = serializer.save()
        recompute_record_aggregates(interval.record)

    def perform_destroy(self, instance):
        record = instance.record
        instance.delete()
        recompute_record_aggregates(record)


# ---------------------------------------------------------------------------
# Debug (superuser / staff only)
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
# Internal helpers
# ---------------------------------------------------------------------------

def _notify_hr_override(record: AttendanceRecord, session: AttendanceSession):
    import threading

    def _send():
        try:
            from django.contrib.auth import get_user_model
            from users.permissions import user_has_role_perm
            from notifications.models import Notification as N

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
            title = f"Devam Kaydı: Manuel Onay Gerekiyor — {user_display}"
            body = (
                f"{user_display} bugün ({record.date}) için manuel devam onayı talep etti.\n"
                f"Neden: {session.override_reason or '—'}"
            )
            for u in hr_users:
                try:
                    N.objects.create(
                        user=u,
                        notification_type=N.PASSWORD_RESET,
                        title=title,
                        body=body,
                        link="/attendance/hr/pending-overrides/",
                        source_type='attendance_record',
                        source_id=record.pk,
                    )
                except Exception:
                    pass
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "attendance: failed to send HR override notification: %s", exc
            )

    threading.Thread(target=_send, daemon=True).start()


def _notify_hr_checkout_override(record: AttendanceRecord, session: AttendanceSession):
    import threading

    def _send():
        try:
            from django.contrib.auth import get_user_model
            from users.permissions import user_has_role_perm
            from notifications.models import Notification as N

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
                f"Neden: {session.override_reason or '—'}"
            )
            for u in hr_users:
                try:
                    N.objects.create(
                        user=u,
                        notification_type=N.PASSWORD_RESET,
                        title=title,
                        body=body,
                        link="/attendance/hr/pending-overrides/",
                        source_type='attendance_record',
                        source_id=record.pk,
                    )
                except Exception:
                    pass
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "attendance: failed to send HR checkout override notification: %s", exc
            )

    threading.Thread(target=_send, daemon=True).start()
