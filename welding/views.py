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
from django.shortcuts import get_object_or_404
from collections import defaultdict
from decimal import Decimal

from .models import WeldingTimeEntry, InternalTeamAssignment, WeldingPlanAllocation
from .serializers import (
    WeldingTimeEntrySerializer,
    WeldingTimeEntryBulkCreateSerializer,
    InternalTeamAssignmentSerializer,
    WeldingPlanAllocationSerializer,
    WeldingPlanAllocationBulkItemSerializer,
)
from .filters import WeldingTimeEntryFilter
from users.helpers import get_dept_code_for_user
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
            user_permissions__codename='access_manufacturing_welding',
        ).select_related('profile', 'profile__position').distinct().order_by('first_name', 'last_name', 'username')

        # Format response
        employees = [
            {
                'id': user.id,
                'username': user.username,
                'full_name': f"{user.first_name} {user.last_name}".strip() or user.username,
                'team': get_dept_code_for_user(user),
                'position': user.profile.position.title if hasattr(user, 'profile') and user.profile.position_id else None,
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


class WeldingPlanAllocationViewSet(viewsets.ModelViewSet):
    """
    Welding capacity-planning allocations: split a MAIN welding task's weight (kg)
    across subcontractors and internal teams, freely and instantly (no money).

    Endpoints:
      GET  /welding/plan-allocations/board/           — grouped snapshot for the Gantt
      POST /welding/plan-allocations/bulk-save/       — create/update/delete in one atomic call
      POST /welding/plan-allocations/{id}/promote/    — convert into a real assignment
      + standard CRUD for one-off edits.
    """
    serializer_class = WeldingPlanAllocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = WeldingPlanAllocation.objects.select_related(
            'department_task__job_order',
            'subcontractor',
            'team',
            'promoted_subcontracting_assignment__department_task',
            'promoted_internal_team_assignment__department_task',
            'created_by',
            'updated_by',
        )
        job_no = self.request.query_params.get('job_no')
        if job_no:
            qs = qs.filter(department_task__job_order_id=job_no)
        return qs

    def destroy(self, request, *args, **kwargs):
        # Serialize deletion with promotion. Without this lock, a DELETE racing a
        # promotion can remove the plan row after the real assignment is created.
        instance = self.get_object()
        with transaction.atomic():
            locked = get_object_or_404(
                WeldingPlanAllocation.objects.select_for_update(),
                pk=instance.pk,
            )
            if locked.is_promoted:
                return Response(
                    {'detail': 'Gerçek atamaya dönüştürülmüş tahsis silinemez.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            self.perform_destroy(locked)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # -- board ---------------------------------------------------------------
    def _append_committed_rows(self, alloc_by_resource, alloc_total_by_task, visible_task_ids=None):
        """Add read-only rows for real assignments made outside the planning flow.

        Their planned dates live on the real subtask's target_start_date/target_completion_date
        (editable via the set-subtask-dates action). visible_task_ids, when given, restricts to
        those welding tasks (used to hide completed jobs).
        """
        from subcontracting.models import SubcontractingAssignment

        welding_parent = (
            Q(department_task__parent__task_type='welding')
            | Q(department_task__parent__title='Kaynaklı İmalat')
        )

        def committed_row(source, source_id, welding_task, resource_type, resource_id, weight, subtask):
            return {
                'id': None,
                'kind': 'committed',
                'source': source,
                'source_id': source_id,
                'subtask_id': subtask.pk,
                'department_task_id': welding_task.pk,
                'job_no': welding_task.job_order_id,
                'job_order_title': welding_task.job_order.title if welding_task.job_order_id else None,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'subcontractor': resource_id if resource_type == 'subcontractor' else None,
                'team': resource_id if resource_type == 'team' else None,
                'allocated_weight_kg': weight,
                'planned_start_date': subtask.target_start_date,
                'planned_end_date': subtask.target_completion_date,
                'notes': '',
                'progress': float(subtask.get_completion_percentage(skip_expensive_calculations=True)),
                'is_promoted': True,  # committed → real work, weight/resource read-only in the UI
            }

        committed_sub = (
            SubcontractingAssignment.objects
            .filter(welding_parent, source_plan_allocation__isnull=True)
            .select_related('subcontractor', 'department_task__parent__job_order')
        )
        for a in committed_sub:
            wt = a.department_task.parent
            if not wt or (visible_task_ids is not None and wt.pk not in visible_task_ids):
                continue
            key = ('subcontractor', a.subcontractor_id)
            alloc_by_resource[key].append(committed_row(
                'subcontracting_assignment', a.id, wt, 'subcontractor',
                a.subcontractor_id, a.allocated_weight_kg, a.department_task,
            ))
            alloc_total_by_task[wt.pk] += a.allocated_weight_kg

        committed_team = (
            InternalTeamAssignment.objects
            .filter(welding_parent, source_plan_allocation__isnull=True)
            .select_related('team', 'department_task__parent__job_order')
        )
        for a in committed_team:
            wt = a.department_task.parent
            if not wt or (visible_task_ids is not None and wt.pk not in visible_task_ids):
                continue
            key = ('team', a.team_id)
            alloc_by_resource[key].append(committed_row(
                'internal_team_assignment', a.id, wt, 'team',
                a.team_id, a.allocated_weight_kg, a.department_task,
            ))
            alloc_total_by_task[wt.pk] += a.allocated_weight_kg

    def _build_board(self, request):
        from subcontracting.models import Subcontractor
        from teams.models import Team
        from projects.models import JobOrderDepartmentTask
        from .services.plan_allocation import build_overallocation_warnings

        include_completed = str(request.query_params.get('include_completed', '')).lower() == 'true'
        HIDDEN_STATUSES = ('completed', 'skipped', 'cancelled')

        # Welding tasks (the draggable jobs). Completed/skipped/cancelled are hidden by default.
        main_qs = (
            JobOrderDepartmentTask.objects
            .filter(Q(task_type='welding') | Q(title='Kaynaklı İmalat'))
            .select_related('job_order', 'job_order__customer')
        )
        if not include_completed:
            main_qs = main_qs.exclude(status__in=HIDDEN_STATUSES)
        main_tasks = list(main_qs)
        visible_task_ids = None if include_completed else {t.pk for t in main_tasks}

        allocations = list(
            WeldingPlanAllocation.objects.select_related(
                'department_task__job_order', 'subcontractor', 'team',
                'promoted_subcontracting_assignment__department_task',
                'promoted_internal_team_assignment__department_task',
            )
        )
        ser = WeldingPlanAllocationSerializer(
            allocations, many=True, context={'request': request}
        ).data
        ser_by_id = {row['id']: row for row in ser}

        # Group serialized allocations by resource key.
        alloc_by_resource = defaultdict(list)
        alloc_total_by_task = defaultdict(Decimal)
        for alloc in allocations:
            if visible_task_ids is not None and alloc.department_task_id not in visible_task_ids:
                continue
            key = ('subcontractor', alloc.subcontractor_id) if alloc.subcontractor_id \
                else ('team', alloc.team_id)
            alloc_by_resource[key].append(ser_by_id[alloc.id])
            alloc_total_by_task[alloc.department_task_id] += alloc.allocated_weight_kg

        # Existing committed assignments (subcontractor/team) that were NOT created via this
        # planning flow (no source_plan_allocation) already represent real work — surface them
        # as read-only board rows so their weight counts and they're visible. Their planned
        # dates come from the real subtask's target dates.
        self._append_committed_rows(alloc_by_resource, alloc_total_by_task, visible_task_ids)

        resources = []
        for sub in Subcontractor.objects.filter(is_active=True):
            rows = alloc_by_resource.get(('subcontractor', sub.id), [])
            resources.append({
                'resource_type': 'subcontractor',
                'id': sub.id,
                'name': sub.name,
                'total_kg': sum((Decimal(str(r['allocated_weight_kg'])) for r in rows), Decimal('0')),
                'allocations': rows,
            })
        for team in Team.objects.filter(is_active=True):
            rows = alloc_by_resource.get(('team', team.id), [])
            resources.append({
                'resource_type': 'team',
                'id': team.id,
                'name': team.name,
                'total_kg': sum((Decimal(str(r['allocated_weight_kg'])) for r in rows), Decimal('0')),
                'allocations': rows,
            })

        welding_tasks = []
        for task in main_tasks:
            job_order = task.job_order if task.job_order_id else None
            total_weight_kg = getattr(job_order, 'total_weight_kg', None) if job_order else None
            allocated_total = alloc_total_by_task.get(task.pk, Decimal('0'))
            customer = getattr(job_order, 'customer', None) if job_order else None
            welding_tasks.append({
                'department_task_id': task.pk,
                'job_no': task.job_order_id,
                'job_order_title': job_order.title if job_order else None,
                'customer_name': customer.name if customer else None,
                'target_completion_date': job_order.target_completion_date if job_order else None,
                'total_weight_kg': total_weight_kg,
                'allocated_total': allocated_total,
                'over_allocated': bool(total_weight_kg is not None and allocated_total > total_weight_kg),
            })

        warnings = build_overallocation_warnings(list(alloc_total_by_task.keys()))
        return {'resources': resources, 'welding_tasks': welding_tasks, 'warnings': warnings}

    @action(detail=False, methods=['get'], url_path='board')
    def board(self, request):
        return Response(self._build_board(request))

    # -- schedule a real subtask (committed / promoted) ----------------------
    @action(detail=False, methods=['post'], url_path='set-subtask-dates')
    def set_subtask_dates(self, request):
        """
        Set planned dates on a REAL welding subtask (a subcontracting/internal_team subtask
        under a welding task). Stores them on the subtask's target_start_date/
        target_completion_date — the same fields the department-tasks Gantt uses.

        POST body: { subtask_id, planned_start_date, planned_end_date }  (dates may be null)
        """
        from rest_framework.exceptions import ValidationError
        from projects.models import JobOrderDepartmentTask

        subtask_id = request.data.get('subtask_id')
        start = request.data.get('planned_start_date') or None
        end = request.data.get('planned_end_date') or None

        if not subtask_id:
            raise ValidationError({'subtask_id': 'subtask_id gereklidir.'})

        try:
            subtask = JobOrderDepartmentTask.objects.select_related('parent').get(pk=subtask_id)
        except JobOrderDepartmentTask.DoesNotExist:
            raise ValidationError({'subtask_id': 'Alt görev bulunamadı.'})

        # Only real welding sub-subtasks may be scheduled here.
        parent = subtask.parent
        is_welding_parent = bool(parent) and (
            parent.task_type == 'welding' or parent.title == 'Kaynaklı İmalat'
        )
        if subtask.task_type not in ('subcontracting', 'internal_team') or not is_welding_parent:
            raise ValidationError({'subtask_id': 'Bu görev planlanabilir bir kaynak alt görevi değil.'})

        subtask.target_start_date = start
        subtask.target_completion_date = end
        subtask.save(update_fields=['target_start_date', 'target_completion_date'])

        return Response(self._build_board(request))

    # -- bulk save -----------------------------------------------------------
    @action(detail=False, methods=['post'], url_path='bulk-save')
    def bulk_save(self, request):
        from rest_framework.exceptions import ValidationError

        items = request.data.get('items', [])
        item_ser = WeldingPlanAllocationBulkItemSerializer(data=items, many=True)
        item_ser.is_valid(raise_exception=True)

        # A ValidationError raised anywhere in here propagates out of the atomic block
        # (rolling the whole save back) and DRF renders it as a 400.
        with transaction.atomic():
            for item in item_ser.validated_data:
                alloc_id = item.get('id')
                deleted = item.get('deleted', False)
                data = {k: v for k, v in item.items() if k not in ('id', 'deleted')}

                if not alloc_id:
                    if deleted:
                        continue
                    ser = WeldingPlanAllocationSerializer(
                        data=data, context={'request': request}
                    )
                    ser.is_valid(raise_exception=True)
                    ser.save()
                    continue

                try:
                    inst = (
                        WeldingPlanAllocation.objects
                        .select_for_update()
                        .get(pk=alloc_id)
                    )
                except WeldingPlanAllocation.DoesNotExist:
                    raise ValidationError(f'Tahsis bulunamadı: {alloc_id}')

                if inst.is_promoted:
                    raise ValidationError(
                        'Gerçek atamaya dönüştürülmüş tahsis düzenlenemez/silinemez.'
                    )

                if deleted:
                    inst.delete()
                    continue

                ser = WeldingPlanAllocationSerializer(
                    inst, data=data, partial=True, context={'request': request}
                )
                ser.is_valid(raise_exception=True)
                ser.save()

        board = self._build_board(request)
        return Response({'saved': True, 'warnings': board['warnings'], 'board': board})

    # -- promote -------------------------------------------------------------
    @action(detail=True, methods=['post'], url_path='promote')
    def promote(self, request, pk=None):
        alloc = self.get_object()
        if alloc.is_promoted:
            return Response(
                {'detail': 'Bu tahsis zaten gerçek atamaya dönüştürülmüş.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # Promotion creates a real production subtask and, for subcontractors,
                # a billable assignment. Re-read under a row lock so concurrent retries
                # cannot both pass the is_promoted check and create duplicate work.
                alloc = get_object_or_404(
                    WeldingPlanAllocation.objects.select_for_update(),
                    pk=alloc.pk,
                )
                if alloc.is_promoted:
                    return Response(
                        {'detail': 'Bu tahsis zaten gerçek atamaya dönüştürülmüş.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                main_task = alloc.department_task
                if alloc.team_id:
                    from .services.internal_team import create_internal_team_assignment
                    _, assignment = create_internal_team_assignment(
                        parent_task=main_task,
                        team=alloc.team,
                        allocated_weight_kg=alloc.allocated_weight_kg,
                        notes=alloc.notes or '',
                        created_by=request.user,
                    )
                    alloc.promoted_internal_team_assignment = assignment
                else:
                    price_tier_id = request.data.get('price_tier')
                    if not price_tier_id:
                        return Response(
                            {'detail': 'Taşeron ataması için price_tier gereklidir.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    from subcontracting.services.assignments import (
                        create_subcontracting_assignment_with_subtask,
                    )
                    assignment = create_subcontracting_assignment_with_subtask(
                        kaynak_task=main_task,
                        subcontractor_id=alloc.subcontractor_id,
                        price_tier_id=price_tier_id,
                        allocated_weight_kg=alloc.allocated_weight_kg,
                        created_by=request.user,
                        context={'request': request},
                    )
                    alloc.promoted_subcontracting_assignment = assignment

                # Carry the plan dates onto the real subtask so scheduling stays continuous.
                if alloc.planned_start_date or alloc.planned_end_date:
                    subtask = assignment.department_task
                    subtask.target_start_date = alloc.planned_start_date
                    subtask.target_completion_date = alloc.planned_end_date
                    subtask.save(update_fields=['target_start_date', 'target_completion_date'])

                alloc.updated_by = request.user
                alloc.save(update_fields=[
                    'promoted_subcontracting_assignment',
                    'promoted_internal_team_assignment',
                    'updated_by', 'updated_at',
                ])
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            WeldingPlanAllocationSerializer(alloc, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


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
