from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from django.db.models import Sum
from django.db import transaction
from django.contrib.auth import get_user_model
from collections import defaultdict

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


class WeldingJobCostListView(APIView):
    """
    GET /welding/reports/job-costs/?job_no=283
    Returns 1 row per job_no with hours + cost breakdown by overtime_type.

    Response:
    {
      "count": 2,
      "results": [
        {
          "job_no": "001-23",
          "hours": {
            "regular": 120.0,
            "after_hours": 30.0,
            "holiday": 10.0
          },
          "costs": {
            "regular": 5400.0,
            "after_hours": 2025.0,
            "holiday": 900.0
          },
          "total_cost": 8325.0,
          "currency": "EUR",
          "updated_at": "2024-01-15T12:00:00Z"
        }
      ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Max
        from welding.models import WeldingJobCostAgg

        job_no = (request.query_params.get("job_no") or "").strip()
        ordering = (request.query_params.get("ordering") or "-total_cost").strip()

        qs = WeldingJobCostAgg.objects.all()
        if job_no:
            qs = qs.filter(job_no__icontains=job_no)

        agg = (
            qs.values("job_no")
            .annotate(
                hours_regular=Sum("hours_regular"),
                hours_after_hours=Sum("hours_after_hours"),
                hours_holiday=Sum("hours_holiday"),
                cost_regular=Sum("cost_regular"),
                cost_after_hours=Sum("cost_after_hours"),
                cost_holiday=Sum("cost_holiday"),
                total_cost=Sum("total_cost"),
                updated_at=Max("updated_at"),
            )
        )

        allowed = {
            "job_no": "job_no", "-job_no": "-job_no",
            "total_cost": "total_cost", "-total_cost": "-total_cost",
            "updated_at": "updated_at", "-updated_at": "-updated_at",
        }
        agg = agg.order_by(allowed.get(ordering, "-total_cost"))

        results = []
        for row in agg:
            item = {
                "job_no": row["job_no"],
                "hours": {
                    "regular": float(row["hours_regular"] or 0),
                    "after_hours": float(row["hours_after_hours"] or 0),
                    "holiday": float(row["hours_holiday"] or 0),
                },
                "costs": {
                    "regular": float(row["cost_regular"] or 0),
                    "after_hours": float(row["cost_after_hours"] or 0),
                    "holiday": float(row["cost_holiday"] or 0),
                },
                "total_cost": float(row["total_cost"] or 0),
                "currency": "EUR",
                "updated_at": row["updated_at"],
            }
            results.append(item)

        return Response({"count": len(results), "results": results}, status=200)


class WeldingJobCostDetailView(APIView):
    """
    GET /welding/reports/job-costs/<job_no>/
    GET /welding/reports/job-costs/?job_no=283

    Returns per-user rows for a specific job with hours + cost breakdown by overtime_type.

    Response:
    {
      "count": 3,
      "results": [
        {
          "user_id": 1,
          "user": "john.doe",
          "hours": {
            "regular": 40.0,
            "after_hours": 10.0,
            "holiday": 0.0
          },
          "costs": {
            "regular": 1800.0,
            "after_hours": 675.0,
            "holiday": 0.0
          },
          "total_cost": 2475.0,
          "currency": "EUR",
          "updated_at": "2024-01-15T12:00:00Z"
        }
      ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, job_no: str | None = None):
        from django.db.models import Sum, Max
        from welding.models import WeldingJobCostAggUser
        from welding.permissions import can_view_all_money, can_view_all_users_hours, can_view_header_totals_only

        # ----- access control -----
        if not can_view_all_users_hours(request.user):
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Query params
        job_like = (request.query_params.get("job_no") or "").strip()
        ordering = (request.query_params.get("ordering") or "-total_cost").strip()

        # Filters (exact job or partial)
        if job_like:
            filter_kwargs = {"job_no__icontains": job_like}
        elif job_no:
            filter_kwargs = {"job_no": job_no}
        else:
            return Response({"detail": "Provide job_no path param or ?job_no=..."}, status=400)

        # Per-user aggregation
        users_qs = (
            WeldingJobCostAggUser.objects
            .filter(**filter_kwargs)
            .select_related("user")
            .values("user_id", "user__username", "currency")
            .annotate(
                hours_regular=Sum("hours_regular"),
                hours_after_hours=Sum("hours_after_hours"),
                hours_holiday=Sum("hours_holiday"),
                cost_regular=Sum("cost_regular"),
                cost_after_hours=Sum("cost_after_hours"),
                cost_holiday=Sum("cost_holiday"),
                total_cost=Sum("total_cost"),
                updated_at=Max("updated_at"),
            )
        )

        # Safe ordering options
        allowed_ordering = {
            "user": "user__username", "-user": "-user__username",
            "total_cost": "total_cost", "-total_cost": "-total_cost",
            "updated_at": "updated_at", "-updated_at": "-updated_at",
        }
        users_qs = users_qs.order_by(allowed_ordering.get(ordering, "-total_cost"))

        # ----- mask money by role -----
        show_full = can_view_all_money(request.user)
        show_hours_only = can_view_header_totals_only(request.user)

        # Assemble payload
        results = []
        for u in users_qs:
            item = {
                "user_id": u["user_id"],
                "user": u["user__username"],
                "hours": {
                    "regular": float(u["hours_regular"] or 0),
                    "after_hours": float(u["hours_after_hours"] or 0),
                    "holiday": float(u["hours_holiday"] or 0),
                },
                "updated_at": u["updated_at"],
            }

            if show_full:
                item["currency"] = u["currency"] or "EUR"
                item["costs"] = {
                    "regular": float(u["cost_regular"] or 0),
                    "after_hours": float(u["cost_after_hours"] or 0),
                    "holiday": float(u["cost_holiday"] or 0),
                }
                item["total_cost"] = float(u["total_cost"] or 0)
            elif show_hours_only:
                item["currency"] = None
                item["costs"] = {"regular": None, "after_hours": None, "holiday": None}
                item["total_cost"] = None

            results.append(item)

        return Response({"count": len(results), "results": results}, status=200)


class UserWorkHoursReportView(APIView):
    """
    GET /welding/user-work-hours-report/?date_after=2025-12-01&date_before=2025-12-31

    Generate a report showing work hours per user between two dates,
    separated by overtime_type and including job numbers.

    Query params:
    - date_after: Required. Start date (YYYY-MM-DD)
    - date_before: Required. End date (YYYY-MM-DD)

    Returns:
    {
        "date_range": {
            "start": "2025-12-01",
            "end": "2025-12-31"
        },
        "users": [
            {
                "employee_id": 1,
                "employee_username": "john.doe",
                "employee_full_name": "John Doe",
                "total_hours": 160.0,
                "by_overtime_type": {
                    "regular": {
                        "hours": 120.0,
                        "job_nos": ["001-23", "002-23"]
                    },
                    "after_hours": {
                        "hours": 30.0,
                        "job_nos": ["001-23"]
                    },
                    "holiday": {
                        "hours": 10.0,
                        "job_nos": ["003-23"]
                    }
                }
            },
            ...
        ]
    }
    """
    permission_classes = [IsWeldingUserOrAdmin]

    def get(self, request):
        date_after = request.query_params.get('date_after')
        date_before = request.query_params.get('date_before')

        # Validate required parameters
        if not date_after or not date_before:
            return Response(
                {'error': 'Both date_after and date_before query parameters are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Query entries within the date range
        entries = WeldingTimeEntry.objects.filter(
            date__gte=date_after,
            date__lte=date_before
        ).select_related('employee').order_by('employee__first_name', 'employee__last_name', 'employee__username')

        # Group data by user
        user_data = defaultdict(lambda: {
            'employee_id': None,
            'employee_username': None,
            'employee_full_name': None,
            'total_hours': 0,
            'by_overtime_type': {
                'regular': {'hours': 0, 'job_nos': set()},
                'after_hours': {'hours': 0, 'job_nos': set()},
                'holiday': {'hours': 0, 'job_nos': set()},
            }
        })

        for entry in entries:
            user_id = entry.employee.id
            user_info = user_data[user_id]

            # Set user info if not set
            if user_info['employee_id'] is None:
                user_info['employee_id'] = entry.employee.id
                user_info['employee_username'] = entry.employee.username
                full_name = f"{entry.employee.first_name} {entry.employee.last_name}".strip()
                user_info['employee_full_name'] = full_name or entry.employee.username

            # Add hours to total
            user_info['total_hours'] += float(entry.hours)

            # Add hours and job_no to overtime_type breakdown
            overtime_type = entry.overtime_type
            if overtime_type in user_info['by_overtime_type']:
                user_info['by_overtime_type'][overtime_type]['hours'] += float(entry.hours)
                user_info['by_overtime_type'][overtime_type]['job_nos'].add(entry.job_no)

        # Format the response
        users_list = []
        for user_info in user_data.values():
            # Convert sets to sorted lists for job_nos
            formatted_overtime = {}
            for overtime_type, data in user_info['by_overtime_type'].items():
                if data['hours'] > 0:  # Only include overtime types with hours
                    formatted_overtime[overtime_type] = {
                        'hours': data['hours'],
                        'job_nos': sorted(list(data['job_nos']))
                    }

            users_list.append({
                'employee_id': user_info['employee_id'],
                'employee_username': user_info['employee_username'],
                'employee_full_name': user_info['employee_full_name'],
                'total_hours': user_info['total_hours'],
                'by_overtime_type': formatted_overtime
            })

        # Sort users by full name
        users_list.sort(key=lambda x: x['employee_full_name'])

        return Response({
            'date_range': {
                'start': date_after,
                'end': date_before
            },
            'users': users_list
        })
