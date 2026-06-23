import calendar
from datetime import datetime, timezone as dt_tz

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Sum, F, Q, BigIntegerField, ExpressionWrapper
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from machines.models import MachineFault
from tasks.models import Timer


def _parse_period(request):
    """
    Parse optional ?year=YYYY&month=MM query params.
    Returns (year_int, month_int, start_ms, end_ms) or (None, None, None, None).
    """
    year  = request.query_params.get('year')
    month = request.query_params.get('month')
    if not (year and month):
        return None, None, None, None
    try:
        y, m = int(year), int(month)
        if not (1 <= m <= 12):
            return None, None, None, None
        start_dt = datetime(y, m, 1, tzinfo=dt_tz.utc)
        last_day  = calendar.monthrange(y, m)[1]
        end_dt    = datetime(y, m, last_day, 23, 59, 59, 999999, tzinfo=dt_tz.utc)
        return y, m, int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None, None, None, None


class StaffActivityReportView(APIView):
    """
    GET /machines/reports/staff/
    GET /machines/reports/staff/?year=2025&month=6

    Per-user summary of maintenance staff activity:
      - faults_resolved_count
      - timers_count  (completed fault-work timers only)
      - total_timer_seconds
    Only users with at least one resolved fault OR one fault-work timer are included.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fault_ct = ContentType.objects.get_for_model(MachineFault)
        year, month, start_ms, end_ms = _parse_period(request)

        # ── Resolved-fault counts per user ────────────────────────────────────
        fault_filter = Q(faults_resolved__isnull=False)
        if year:
            fault_filter &= Q(
                faults_resolved__resolved_at__year=year,
                faults_resolved__resolved_at__month=month,
            )

        resolver_qs = (
            User.objects
            .filter(fault_filter)
            .annotate(faults_resolved_count=Count('faults_resolved', distinct=True))
        )
        resolver_map = {u.id: u.faults_resolved_count for u in resolver_qs}

        # ── Fault-work timer stats per user ───────────────────────────────────
        timer_filter = {
            'new_started_timers__content_type': fault_ct,
            'new_started_timers__finish_time__isnull': False,
        }
        if start_ms is not None:
            timer_filter['new_started_timers__start_time__gte'] = start_ms
            timer_filter['new_started_timers__start_time__lte'] = end_ms

        timer_qs = (
            User.objects
            .filter(**timer_filter)
            .annotate(
                timers_count=Count('new_started_timers', distinct=True),
                total_timer_ms=Sum(
                    ExpressionWrapper(
                        F('new_started_timers__finish_time') - F('new_started_timers__start_time'),
                        output_field=BigIntegerField(),
                    )
                ),
            )
        )
        timer_map = {
            u.id: {
                'timers_count': u.timers_count,
                'total_timer_ms': u.total_timer_ms or 0,
            }
            for u in timer_qs
        }

        all_user_ids = set(resolver_map.keys()) | set(timer_map.keys())
        users_by_id  = {u.id: u for u in User.objects.filter(id__in=all_user_ids)}

        results = []
        for uid in all_user_ids:
            u  = users_by_id[uid]
            td = timer_map.get(uid, {'timers_count': 0, 'total_timer_ms': 0})
            results.append({
                'user_id': uid,
                'username': u.username,
                'full_name': u.get_full_name() or u.username,
                'faults_resolved_count': resolver_map.get(uid, 0),
                'timers_count': td['timers_count'],
                'total_timer_seconds': (td['total_timer_ms'] or 0) / 1000,
            })

        results.sort(key=lambda x: x['faults_resolved_count'], reverse=True)
        return Response(results)


class StaffActivityDetailView(APIView):
    """
    GET /machines/reports/staff/<user_id>/
    GET /machines/reports/staff/<user_id>/?year=2025&month=6

    Full activity breakdown for a single staff member:
      - user: basic info
      - resolved_faults: list of faults they resolved (with timing)
      - timers: list of fault-work timer sessions
    Both lists are filtered to the requested period when year+month are provided.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        fault_ct = ContentType.objects.get_for_model(MachineFault)
        user     = get_object_or_404(User, pk=user_id)
        year, month, start_ms, end_ms = _parse_period(request)

        # ── Resolved faults ───────────────────────────────────────────────────
        fault_qs = (
            MachineFault.objects
            .filter(resolved_by=user)
            .select_related('machine', 'reported_by')
            .order_by('-resolved_at')
        )
        if year:
            fault_qs = fault_qs.filter(
                resolved_at__year=year,
                resolved_at__month=month,
            )

        fault_list = []
        for f in fault_qs:
            duration_s = None
            if f.reported_at and f.resolved_at:
                duration_s = (f.resolved_at - f.reported_at).total_seconds()
            fault_list.append({
                'id': f.id,
                'machine_name': f.machine.name if f.machine else (f.asset_name or '-'),
                'description': f.description,
                'is_breaking': f.is_breaking,
                'is_maintenance': f.is_maintenance,
                'reported_by': (
                    f.reported_by.get_full_name() or f.reported_by.username
                    if f.reported_by else None
                ),
                'reported_at': f.reported_at,
                'resolved_at': f.resolved_at,
                'resolution_duration_seconds': duration_s,
                'resolution_description': f.resolution_description,
            })

        # ── Fault-work timers (GFK-linked) ────────────────────────────────────
        timer_qs = (
            Timer.objects
            .filter(user=user, content_type=fault_ct)
            .order_by('-start_time')
        )
        if start_ms is not None:
            timer_qs = timer_qs.filter(
                start_time__gte=start_ms,
                start_time__lte=end_ms,
            )

        timer_list = []
        for t in timer_qs:
            duration_s = None
            if t.start_time is not None and t.finish_time is not None:
                duration_s = (t.finish_time - t.start_time) / 1000

            fault = t.issue_key  # GenericForeignKey → MachineFault (may be None)
            timer_list.append({
                'id': t.id,
                'fault_id': int(t.object_id) if t.object_id else None,
                'fault_description': fault.description if fault else None,
                'fault_machine': (
                    fault.machine.name if fault and fault.machine
                    else (fault.asset_name if fault else None)
                ),
                'fault_is_resolved': bool(fault.resolved_at) if fault else None,
                'start_time_ms': t.start_time,
                'finish_time_ms': t.finish_time,
                'duration_seconds': duration_s,
                'is_active': t.finish_time is None,
                'comment': t.comment,
            })

        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
            },
            'resolved_faults': fault_list,
            'timers': timer_list,
            'period': {'year': year, 'month': month} if year else None,
        })
