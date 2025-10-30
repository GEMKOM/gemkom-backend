from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import User
from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField


class UserResolutionReportView(APIView):
    """
    Provides a report on user performance for resolving machine faults.

    For each user who has resolved at least one fault, it calculates:
    - resolved_faults_count: The total number of faults resolved by the user.
    - average_resolution_time_seconds: The average time taken to resolve a fault, in seconds.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # Define an expression to calculate the duration of each resolved fault.
        resolution_duration = ExpressionWrapper(
            F('faults_resolved__resolved_at') - F('faults_resolved__reported_at'),
            output_field=DurationField()
        )

        # Query users who have resolved faults and annotate with statistics.
        report_qs = User.objects.filter(faults_resolved__isnull=False).annotate(
            resolved_faults_count=Count('faults_resolved'),
            average_resolution_time=Avg(resolution_duration)
        ).values(
            'id', 'username', 'first_name', 'last_name', 'resolved_faults_count', 'average_resolution_time'
        ).order_by('-resolved_faults_count')

        # Convert DurationField to total seconds for a more portable JSON response.
        results = [
            {**item, 'average_resolution_time_seconds': item['average_resolution_time'].total_seconds()}
            for item in report_qs
        ]

        return Response(results)