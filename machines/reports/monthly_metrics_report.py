from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from machines.models import MachineFault


class MonthlyMetricsReportView(APIView):
    """
    GET /machines/reports/monthly-metrics/

    Returns per-month aggregated metrics for the last 12 months (or as many as exist):
      - period:                  "YYYY-MM"
      - total_faults:            all faults reported that month
      - breaking_faults:         faults where is_breaking=True
      - maintenance_faults:      faults where is_maintenance=True
      - resolved_faults:         faults resolved that month
      - unresolved_faults:       still-open faults reported that month
      - avg_resolution_seconds:  mean time-to-resolve (only resolved faults, in seconds)
      - min_resolution_seconds:  fastest resolution that month
      - max_resolution_seconds:  slowest resolution that month
      - avg_breaking_downtime_seconds: mean machine downtime per breaking fault
      - total_breaking_downtime_seconds: total machine downtime that month
      - unique_machines_affected: distinct machines with at least one fault
      - unique_resolvers:        distinct users who resolved at least one fault

    Also returns overall summary across all months:
      - overall_avg_resolution_seconds
      - overall_avg_faults_per_month
      - overall_avg_breaking_per_month
      - busiest_month (period with most faults)
      - fastest_month (period with lowest avg resolution time, resolved faults only)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ── Per-month data (grouped by month of reported_at) ──────────────────
        monthly_qs = (
            MachineFault.objects
            .annotate(month=TruncMonth('reported_at'))
            .values('month')
            .annotate(
                total_faults=Count('id'),
                breaking_faults=Count('id', filter=Q(is_breaking=True)),
                maintenance_faults=Count('id', filter=Q(is_maintenance=True)),
                resolved_faults=Count('id', filter=Q(resolved_at__isnull=False)),
                unresolved_faults=Count('id', filter=Q(resolved_at__isnull=True)),
                unique_machines_affected=Count('machine', distinct=True, filter=Q(machine__isnull=False)),
                unique_resolvers=Count('resolved_by', distinct=True, filter=Q(resolved_by__isnull=False)),
            )
            .order_by('month')
        )

        # Compute min/max/avg in Python (cleaner than nested subqueries on DurationField).
        resolved_raw = (
            MachineFault.objects
            .filter(resolved_at__isnull=False)
            .annotate(month=TruncMonth('reported_at'))
            .values('month', 'reported_at', 'resolved_at', 'is_breaking',
                    'downtime_start_ms', 'downtime_end_ms')
        )

        # Group resolved faults by month for min/max/avg and downtime
        from collections import defaultdict
        month_resolutions = defaultdict(list)      # month → [duration_seconds]
        month_downtime    = defaultdict(list)      # month → [downtime_seconds]

        for row in resolved_raw:
            m   = row['month']
            dur = (row['resolved_at'] - row['reported_at']).total_seconds()
            month_resolutions[m].append(dur)
            if row['is_breaking'] and row['downtime_start_ms'] and row['downtime_end_ms']:
                dt_s = (row['downtime_end_ms'] - row['downtime_start_ms']) / 1000
                month_downtime[m].append(dt_s)

        # Build result list
        results = []
        for row in monthly_qs:
            m = row['month']
            durations = month_resolutions.get(m, [])
            downtimes  = month_downtime.get(m, [])

            avg_res = (sum(durations) / len(durations)) if durations else None
            min_res = min(durations) if durations else None
            max_res = max(durations) if durations else None
            avg_dt  = (sum(downtimes) / len(downtimes)) if downtimes else None
            tot_dt  = sum(downtimes) if downtimes else None

            results.append({
                'period': m.strftime('%Y-%m'),
                'period_label': m.strftime('%B %Y'),   # will be in English; formatted client-side
                'total_faults':       row['total_faults'],
                'breaking_faults':    row['breaking_faults'],
                'maintenance_faults': row['maintenance_faults'],
                'resolved_faults':    row['resolved_faults'],
                'unresolved_faults':  row['unresolved_faults'],
                'resolve_rate_pct': (
                    round(row['resolved_faults'] / row['total_faults'] * 100, 1)
                    if row['total_faults'] else None
                ),
                'avg_resolution_seconds': round(avg_res, 0) if avg_res is not None else None,
                'min_resolution_seconds': round(min_res, 0) if min_res is not None else None,
                'max_resolution_seconds': round(max_res, 0) if max_res is not None else None,
                'avg_breaking_downtime_seconds': round(avg_dt, 0) if avg_dt is not None else None,
                'total_breaking_downtime_seconds': round(tot_dt, 0) if tot_dt is not None else None,
                'unique_machines_affected': row['unique_machines_affected'],
                'unique_resolvers': row['unique_resolvers'],
            })

        # ── Overall summary ───────────────────────────────────────────────────
        all_durations = [d for dlist in month_resolutions.values() for d in dlist]
        months_with_data = len(results)

        overall_avg_res = (sum(all_durations) / len(all_durations)) if all_durations else None
        overall_avg_faults = (
            sum(r['total_faults'] for r in results) / months_with_data
            if months_with_data else None
        )
        overall_avg_breaking = (
            sum(r['breaking_faults'] for r in results) / months_with_data
            if months_with_data else None
        )

        busiest = max(results, key=lambda r: r['total_faults'], default=None)
        fastest = min(
            (r for r in results if r['avg_resolution_seconds'] is not None),
            key=lambda r: r['avg_resolution_seconds'],
            default=None
        )

        summary = {
            'overall_avg_resolution_seconds': round(overall_avg_res, 0) if overall_avg_res is not None else None,
            'overall_avg_faults_per_month':   round(overall_avg_faults, 1) if overall_avg_faults is not None else None,
            'overall_avg_breaking_per_month': round(overall_avg_breaking, 1) if overall_avg_breaking is not None else None,
            'busiest_month': busiest['period'] if busiest else None,
            'fastest_month': fastest['period'] if fastest else None,
            'total_faults_all_time': sum(r['total_faults'] for r in results),
            'total_resolved_all_time': sum(r['resolved_faults'] for r in results),
            'total_breaking_downtime_all_time': sum(
                r['total_breaking_downtime_seconds'] or 0 for r in results
            ),
        }

        return Response({'monthly': results, 'summary': summary})
