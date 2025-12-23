from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from django.db.models import Sum, Q
from django.db import transaction
from django.contrib.auth import get_user_model

from .models import WeldingTimeEntry
from .serializers import WeldingTimeEntrySerializer, WeldingTimeEntryBulkCreateSerializer
from .filters import WeldingTimeEntryFilter
from .permissions import IsWeldingUserOrAdmin
from users.permissions import IsAdmin
from config.pagination import CustomPageNumberPagination

User = get_user_model()


class WeldingTimeEntryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for CRUD operations on WeldingTimeEntry.

    Supports:
    - List: GET /welding/time-entries/
    - Create: POST /welding/time-entries/
    - Retrieve: GET /welding/time-entries/{id}/
    - Update: PUT/PATCH /welding/time-entries/{id}/
    - Delete: DELETE /welding/time-entries/{id}/
    - Custom action for job hours: GET /welding/time-entries/job-hours/?job_no=001
    """
    queryset = WeldingTimeEntry.objects.all()
    serializer_class = WeldingTimeEntrySerializer
    permission_classes = [IsWeldingUserOrAdmin]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = WeldingTimeEntryFilter
    pagination_class = CustomPageNumberPagination
    ordering_fields = ['date', 'employee', 'job_no', 'hours', 'created_at']
    ordering = ['-date', 'employee']

    def get_queryset(self):
        """Optimize queryset with select_related."""
        return WeldingTimeEntry.objects.select_related(
            'employee',
            'created_by',
            'updated_by'
        )

    @action(detail=False, methods=['get'], url_path='active-employees')
    def active_employees(self, request):  # noqa: ARG002
        """
        Get list of active welding employees for dropdowns/selection.

        Returns only active users (is_active=True) in the welding team.
        Historical data will still show inactive employees, but they won't
        appear in this list for new entries.

        GET /welding/time-entries/active-employees/

        Returns:
        [
            {
                "id": 5,
                "username": "john.doe",
                "full_name": "John Doe",
                "team": "welding",
                "occupation": "welder"
            },
            ...
        ]
        """
        # Get active users in welding team
        active_welders = User.objects.filter(
            is_active=True,
            profile__team='welding'
        ).select_related('profile').order_by('first_name', 'last_name', 'username')

        # Format response
        employees = [
            {
                'id': user.id,
                'username': user.username,
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'team': user.profile.team if hasattr(user, 'profile') else None,
                'occupation': user.profile.occupation if hasattr(user, 'profile') else None,
            }
            for user in active_welders
        ]

        return Response(employees)

    @action(detail=False, methods=['get'], url_path='job-hours')
    def job_hours(self, request):
        """
        Get aggregated hours for a specific job_no (supports partial matching).

        Query params:
        - job_no: Required. Job number to search (supports partial matching with 'icontains')
        - date_after: Optional. Filter entries after this date (YYYY-MM-DD)
        - date_before: Optional. Filter entries before this date (YYYY-MM-DD)

        Returns:
        {
            "job_no": "001-23",
            "total_hours": 45.50,
            "entry_count": 12,
            "breakdown_by_employee": [
                {
                    "employee_id": 1,
                    "employee_username": "john.doe",
                    "employee_full_name": "John Doe",
                    "hours": 20.00,
                    "entry_count": 5
                },
                ...
            ],
            "breakdown_by_date": [
                {
                    "date": "2025-12-20",
                    "hours": 15.50,
                    "entry_count": 3
                },
                ...
            ]
        }
        """
        job_no = request.query_params.get('job_no')
        if not job_no:
            return Response(
                {'error': 'job_no query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Build queryset with filters
        queryset = self.get_queryset().filter(job_no__icontains=job_no)

        # Apply optional date filters
        date_after = request.query_params.get('date_after')
        date_before = request.query_params.get('date_before')
        if date_after:
            queryset = queryset.filter(date__gte=date_after)
        if date_before:
            queryset = queryset.filter(date__lte=date_before)

        # Aggregate total hours
        aggregates = queryset.aggregate(
            total_hours=Sum('hours'),
            entry_count=Sum('id') * 0 + queryset.count()  # Count entries
        )

        # Breakdown by employee
        employee_breakdown = (
            queryset
            .values('employee', 'employee__username', 'employee__first_name', 'employee__last_name')
            .annotate(
                hours=Sum('hours'),
                entry_count=Sum('id') * 0 + 1  # This is a trick to count per group
            )
            .order_by('-hours')
        )

        # Format employee breakdown
        formatted_employee_breakdown = [
            {
                'employee_id': item['employee'],
                'employee_username': item['employee__username'],
                'employee_full_name': f"{item['employee__first_name']} {item['employee__last_name']}".strip() or item['employee__username'],
                'hours': float(item['hours']) if item['hours'] else 0,
                'entry_count': queryset.filter(employee=item['employee']).count()
            }
            for item in employee_breakdown
        ]

        # Breakdown by date
        date_breakdown = (
            queryset
            .values('date')
            .annotate(
                hours=Sum('hours'),
                entry_count=Sum('id') * 0 + 1
            )
            .order_by('-date')
        )

        # Format date breakdown
        formatted_date_breakdown = [
            {
                'date': item['date'].isoformat(),
                'hours': float(item['hours']) if item['hours'] else 0,
                'entry_count': queryset.filter(date=item['date']).count()
            }
            for item in date_breakdown
        ]

        return Response({
            'job_no': job_no,
            'total_hours': float(aggregates['total_hours']) if aggregates['total_hours'] else 0,
            'entry_count': aggregates['entry_count'],
            'breakdown_by_employee': formatted_employee_breakdown,
            'breakdown_by_date': formatted_date_breakdown,
        })


class WeldingTimeEntryBulkCreateView(APIView):
    """
    Bulk create welding time entries.

    POST /welding/time-entries/bulk-create/

    Request body:
    {
        "entries": [
            {
                "employee": 1,
                "job_no": "001-23",
                "date": "2025-12-20",
                "hours": 8.0,
                "description": "Welding main frame"
            },
            {
                "employee": 2,
                "job_no": "002-23",
                "date": "2025-12-20",
                "hours": 6.5,
                "description": "Welding support structure"
            }
        ]
    }

    Returns:
    {
        "created_count": 2,
        "entries": [...]
    }
    """
    permission_classes = [IsWeldingUserOrAdmin]

    def post(self, request):
        serializer = WeldingTimeEntryBulkCreateSerializer(
            data=request.data,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                result = serializer.save()
                entries = result['entries']

                # Serialize the created entries for response
                response_serializer = WeldingTimeEntrySerializer(entries, many=True)

                return Response({
                    'created_count': len(entries),
                    'entries': response_serializer.data
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': f'Failed to create entries: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
