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

from .models import WeldingTimeEntry, InternalTeamAssignment
from .serializers import (
    WeldingTimeEntrySerializer,
    WeldingTimeEntryBulkCreateSerializer,
    InternalTeamAssignmentSerializer,
)
from .filters import WeldingTimeEntryFilter
from users.helpers import primary_team_from_groups
from rest_framework.permissions import IsAuthenticated
from users.permissions import IsAdmin, can_see_job_costs
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
    permission_classes = [IsAuthenticated]
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
            groups__name='welding_team'
        ).select_related('profile').order_by('first_name', 'last_name', 'username')

        # Format response
        employees = [
            {
                'id': user.id,
                'username': user.username,
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'team': primary_team_from_groups(user),
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


class InternalTeamAssignmentViewSet(viewsets.ModelViewSet):
    """
    CRUD for InternalTeamAssignment.

    Filtering:
      ?job_no=254-01      — all assignments for a specific job order
      ?department_task=42 — assignment for a specific task (or its subtasks)

    Creation is handled exclusively through the create-with-subtask action.
    Deletion is handled exclusively through the delete-with-subtask action.
    """
    serializer_class = InternalTeamAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = InternalTeamAssignment.objects.select_related(
            'department_task__job_order',
            'team__foreman',
            'created_by',
            'updated_by',
        )
        job_no = self.request.query_params.get('job_no')
        department_task = self.request.query_params.get('department_task')
        if job_no:
            qs = qs.filter(department_task__job_order_id=job_no)
        if department_task:
            from projects.models import JobOrderDepartmentTask
            subtask_ids = list(
                JobOrderDepartmentTask.objects
                .filter(parent_id=department_task)
                .values_list('pk', flat=True)
            )
            qs = qs.filter(department_task_id__in=[int(department_task)] + subtask_ids)
        return qs

    def create(self, request, *args, **kwargs):
        return Response(
            {'detail': 'Doğrudan oluşturmak için create-with-subtask kullanın.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {'detail': 'Silmek için delete-with-subtask kullanın.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=False, methods=['post'], url_path='create-with-subtask')
    def create_with_subtask(self, request):
        """
        Atomically create an internal_team subtask and its assignment.

        POST /welding/internal-team-assignments/create-with-subtask/

        Body:
          welding_task_id      (int, required)     — ID of the Kaynaklı İmalat parent task
          team                 (int, required)      — Team PK
          allocated_weight_kg  (decimal, required)
          title                (str, optional)      — subtask title; defaults to team name
          notes                (str, optional)
        """
        from decimal import Decimal
        from projects.models import JobOrderDepartmentTask
        from teams.models import Team
        from .services.internal_team import create_internal_team_assignment

        welding_task_id = request.data.get('welding_task_id')
        team_id = request.data.get('team')
        allocated_weight_kg = request.data.get('allocated_weight_kg')
        title = str(request.data.get('title', '') or '').strip()
        notes = str(request.data.get('notes', '') or '')

        if not welding_task_id or not team_id or not allocated_weight_kg:
            return Response(
                {'detail': 'welding_task_id, team ve allocated_weight_kg zorunludur.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parent_task = JobOrderDepartmentTask.objects.select_related('job_order').get(pk=welding_task_id)
        except JobOrderDepartmentTask.DoesNotExist:
            return Response({'detail': 'Üst görev bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            team = Team.objects.get(pk=team_id, is_active=True)
        except Team.DoesNotExist:
            return Response({'detail': 'Ekip bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            _, assignment = create_internal_team_assignment(
                parent_task=parent_task,
                team=team,
                allocated_weight_kg=Decimal(str(allocated_weight_kg)),
                title=title,
                notes=notes,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            InternalTeamAssignmentSerializer(assignment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['patch'], url_path='update-assignment')
    def update_assignment(self, request, pk=None):
        """
        Update an internal team assignment and optionally its linked subtask.

        PATCH /welding/internal-team-assignments/{id}/update-assignment/

        Body (all optional):
          team                 — new Team PK
          allocated_weight_kg  — new weight (also updates subtask.weight)
          notes
          title                — new subtask title
          manual_progress      — 0-100; sets department_task.manual_progress
          task_status          — new status for the subtask
        """
        from decimal import Decimal
        from teams.models import Team

        assignment = self.get_object()
        subtask = assignment.department_task

        with transaction.atomic():
            if 'team' in request.data:
                try:
                    assignment.team = Team.objects.get(pk=request.data['team'], is_active=True)
                except Team.DoesNotExist:
                    return Response({'detail': 'Ekip bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

            if 'allocated_weight_kg' in request.data:
                new_weight = Decimal(str(request.data['allocated_weight_kg']))
                assignment.allocated_weight_kg = new_weight
                subtask.weight = max(1, round(new_weight))

            if 'notes' in request.data:
                assignment.notes = request.data['notes']

            assignment.updated_by = request.user
            assignment.save()

            subtask_update_fields = []
            if 'title' in request.data:
                subtask.title = request.data['title']
                subtask_update_fields.append('title')
            if 'manual_progress' in request.data:
                subtask.manual_progress = Decimal(str(request.data['manual_progress']))
                subtask_update_fields.append('manual_progress')
            if 'task_status' in request.data:
                subtask.status = request.data['task_status']
                subtask_update_fields.append('status')
            if 'allocated_weight_kg' in request.data:
                subtask_update_fields.append('weight')

            if subtask_update_fields:
                subtask.save(update_fields=subtask_update_fields)

            if ('manual_progress' in request.data or 'task_status' in request.data) and subtask.job_order_id:
                subtask.job_order.update_completion_percentage()

        return Response(
            InternalTeamAssignmentSerializer(assignment, context={'request': request}).data
        )

    @action(detail=True, methods=['delete'], url_path='delete-with-subtask')
    def delete_with_subtask(self, request, pk=None):
        """
        Delete the assignment AND its linked subtask together.

        DELETE /welding/internal-team-assignments/{id}/delete-with-subtask/
        """
        assignment = self.get_object()
        subtask = assignment.department_task
        job_order = subtask.job_order

        with transaction.atomic():
            subtask.delete()  # CASCADE removes the assignment

        if job_order:
            job_order.update_completion_percentage()

        return Response(status=status.HTTP_204_NO_CONTENT)


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
    permission_classes = [IsAuthenticated]

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


class WeldingJobEntriesReportView(APIView):
    """
    GET /welding/reports/job-entries/?job_no=283

    Lightweight report endpoint for welding time entries for a specific job.
    Returns all entries with minimal fields and summary totals.

    Query params:
    - job_no: Required. Exact job number match (not partial)

    Response:
    {
        "job_no": "283",
        "summary": {
            "total_hours": 45.5,
            "total_entries": 12,
            "breakdown_by_type": {
                "regular": 32.0,
                "after_hours": 10.5,
                "holiday": 3.0
            }
        },
        "entries": [
            {
                "id": 1,
                "employee_id": 5,
                "employee_username": "john.doe",
                "employee_full_name": "John Doe",
                "date": "2025-12-20",
                "hours": 8.0,
                "overtime_type": "regular"
            },
            ...
        ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from decimal import Decimal, ROUND_HALF_UP
        from welding.services.costing import _build_wage_picker, WAGE_MONTH_HOURS
        from machining.fx_utils import build_fx_lookup

        job_no = request.query_params.get('job_no')
        if not job_no:
            return Response(
                {'error': 'job_no query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        show_costs = can_see_job_costs(request.user)

        # Exact match on job_no (not partial/icontains)
        entries = list(
            WeldingTimeEntry.objects.filter(
                job_no=job_no
            ).select_related('employee').order_by('date', 'employee__username')
        )

        # Build cost helpers once (only if needed)
        if show_costs and entries:
            user_ids = {e.employee_id for e in entries}
            pick_wage = _build_wage_picker(user_ids)
            fx = build_fx_lookup('EUR')
            q2 = lambda x: x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        total_hours = 0.0
        total_cost = Decimal('0') if show_costs else None
        breakdown_by_type = defaultdict(float)
        formatted_entries = []

        for entry in entries:
            hrs = float(entry.hours)
            total_hours += hrs
            breakdown_by_type[entry.overtime_type] += hrs

            row = {
                'id': entry.id,
                'employee_id': entry.employee.id,
                'employee_username': entry.employee.username,
                'employee_full_name': f"{entry.employee.first_name} {entry.employee.last_name}".strip() or entry.employee.username,
                'date': entry.date.isoformat(),
                'hours': hrs,
                'overtime_type': entry.overtime_type,
            }

            if show_costs:
                d = entry.date
                wage = pick_wage(entry.employee_id, d)
                entry_cost = Decimal('0')
                if wage:
                    try_to_eur = fx(d)
                    if try_to_eur != 0:
                        base_hourly = Decimal(wage['base_monthly']) / WAGE_MONTH_HOURS
                        ah_mul = Decimal(wage['after_hours_multiplier'])
                        su_mul = Decimal(wage['sunday_multiplier'])
                        dec_hrs = Decimal(str(entry.hours))
                        if entry.overtime_type == 'regular':
                            entry_cost = dec_hrs * base_hourly * try_to_eur
                        elif entry.overtime_type == 'after_hours':
                            entry_cost = dec_hrs * base_hourly * ah_mul * try_to_eur
                        else:  # holiday
                            entry_cost = dec_hrs * base_hourly * su_mul * try_to_eur
                entry_cost = q2(entry_cost)
                total_cost += entry_cost
                row['cost'] = str(entry_cost)
                row['cost_currency'] = 'EUR'

            formatted_entries.append(row)

        summary = {
            'total_hours': total_hours,
            'total_entries': len(formatted_entries),
            'breakdown_by_type': dict(breakdown_by_type),
        }
        if show_costs:
            summary['total_cost'] = str(q2(total_cost)) if entries else '0.00'
            summary['cost_currency'] = 'EUR'

        return Response({
            'job_no': job_no,
            'summary': summary,
            'entries': formatted_entries,
        })


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
    permission_classes = [IsAuthenticated]

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
