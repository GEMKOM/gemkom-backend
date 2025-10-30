from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Sum, Q, F, ExpressionWrapper, DurationField, Value, Case, When, DateTimeField
from datetime import timedelta
from django.db.models.functions import Coalesce
from django.utils import timezone

from machines.models import Machine


class MachineFaultsSummaryReportView(APIView):
    """
    Provides a summary report of machine faults, grouped by machine.

    For each machine, it calculates:
    - total_faults: The total number of faults reported for the machine.
    - breaking_faults_count: The number of faults where `is_breaking` is True.
    - total_breaking_downtime_seconds: The total downtime (in seconds) for resolved breaking faults.
    - total_non_breaking_duration_seconds: The total duration for non-breaking faults.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        now = timezone.now() # Get current time once for consistent calculations

        # Define an expression to get the resolved_at timestamp,
        # using 'now' for unresolved faults.
        resolved_at_or_now = Case(
            When(faults__resolved_at__isnull=False, then=F('faults__resolved_at')),
            default=Value(now, output_field=DateTimeField())
        )

        # Define an expression to calculate the duration of each fault,
        # using the resolved_at_or_now expression.
        fault_duration = ExpressionWrapper(
            resolved_at_or_now - F('faults__reported_at'),
            output_field=DurationField()
        )

        # Annotate machines with fault statistics.
        report_qs = Machine.objects.filter(faults__isnull=False).annotate( # Only include machines with at least one fault
            total_faults=Count('faults'),
            breaking_faults_count=Count('faults', filter=Q(faults__is_breaking=True)),
            total_breaking_downtime=Coalesce(
                Sum(
                    fault_duration, # Sum durations for all breaking faults
                    filter=Q(faults__is_breaking=True)
                ),
                Value(timedelta(seconds=0), output_field=DurationField())
            ),
            total_non_breaking_duration=Coalesce(
                Sum(
                    fault_duration, # Sum durations for all non-breaking faults
                    filter=Q(faults__is_breaking=False)
                ),
                Value(timedelta(seconds=0), output_field=DurationField())
            )
        ).values(
            'id', 'name', 'code', 'total_faults', 'breaking_faults_count',
            'total_breaking_downtime', 'total_non_breaking_duration'
        ).order_by('-total_faults')

        # Convert DurationField to total seconds for a more portable JSON response.
        results = [
            {**item,
             'total_breaking_downtime_seconds': item['total_breaking_downtime'].total_seconds(),
             'total_non_breaking_duration_seconds': item['total_non_breaking_duration'].total_seconds()}
            for item in report_qs
        ]

        return Response(results)