from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, F, ExpressionWrapper, FloatField, Sum, Avg, Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.contrib.contenttypes.models import ContentType
from collections import defaultdict
from django.db import transaction
import time

# Create your views here.
from .models import Timer, Part, Operation, Tool
from .serializers import (
    BaseTimerSerializer, PartSerializer, PartListSerializer, PartWithOperationsSerializer,
    OperationSerializer, OperationDetailSerializer, OperationOperatorSerializer,
    ToolSerializer, OperationPlanUpdateItemSerializer
)
from .filters import OperationFilter, PartFilter
from config.pagination import CustomPageNumberPagination


def _get_task_model_from_type(task_type):
    if task_type == 'machining':
        from machining.models import Task
        return Task
    elif task_type == 'cnc_cutting':
        from cnc_cutting.models import CncTask
        return CncTask
    elif task_type == 'operation':
        from tasks.models import Operation
        return Operation
    return None

def _parse_ms(val):
    """Helper to parse a timestamp (ms or seconds) into milliseconds."""
    if val is None: return None
    ts = int(val)
    return ts * 1000 if ts < 1_000_000_000_000 else ts

def get_timer_serializer_class(task_type):
    """Dynamically returns the appropriate timer serializer."""
    if task_type == 'machining':
        from machining.serializers import TimerSerializer
        return TimerSerializer
    elif task_type == 'cnc_cutting':
        from cnc_cutting.serializers import CncTimerSerializer
        return CncTimerSerializer
    elif task_type == 'operation':
        from tasks.serializers import OperationTimerSerializer
        return OperationTimerSerializer
    return BaseTimerSerializer

class GenericTimerStartView(APIView):
    """
    A generic view to start a timer for any task type.
    The `task_type` is provided via the URL.
    """
    permission_classes = [IsAuthenticated] # You can create more specific permissions later

    def post(self, request, task_type):
        data = request.data.copy()
        # For backward compatibility with frontends that might send 'issue_key'
        if 'issue_key' in data:
            data['task_key'] = data.pop('issue_key')

        data['task_type'] = task_type  # Set from the URL parameter
        data['manual_entry'] = False

        # If task_type is 'operation', validate tool availability and order
        if task_type == 'operation':
            operation_key = data.get('task_key')
            if operation_key:
                try:
                    operation = Operation.objects.select_related('part').prefetch_related('operation_tools__tool').get(key=operation_key)

                    # Validate operation order - non-interchangeable operations must wait for ALL previous operations
                    if not operation.interchangeable:
                        previous_incomplete = Operation.objects.filter(
                            part=operation.part,
                            order__lt=operation.order,
                            completion_date__isnull=True
                        )
                        if previous_incomplete.exists():
                            incomplete_orders = list(previous_incomplete.values_list('order', flat=True))
                            return Response({
                                'error': f"Cannot start timer on operation {operation.order}. All previous operations must be completed first.",
                                'incomplete_operations': incomplete_orders
                            }, status=400)

                    # Validate tool availability
                    for op_tool in operation.operation_tools.all():
                        tool = op_tool.tool
                        if not tool.is_available(op_tool.quantity):
                            available = tool.get_available_quantity()
                            return Response({
                                'error': f"Tool {tool.code} ({tool.name}) not available",
                                'tool_code': tool.code,
                                'required': op_tool.quantity,
                                'available': available
                            }, status=400)

                except Operation.DoesNotExist:
                    return Response({'error': 'Operation not found'}, status=404)

        SerializerClass = get_timer_serializer_class(task_type)
        serializer = SerializerClass(data=data, context={'request': request})
        if serializer.is_valid():
            # Check for existing active timer on the same machine
            machine_id = serializer.validated_data.get('machine_fk')
            if machine_id:
                existing_active_timer = Timer.objects.filter(
                    machine_fk=machine_id,
                    finish_time__isnull=True
                ).first()
                if existing_active_timer:
                    return Response({
                        'error': 'There is already an active timer on this machine. Stop it first before starting a new one.',
                        'existing_timer_id': existing_active_timer.id,
                        'existing_timer_user': existing_active_timer.user.username
                    }, status=status.HTTP_409_CONFLICT)

            timer = serializer.save()
            return Response({"id": timer.id}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GenericTimerStopView(APIView):
    """
    A generic view to stop a timer. This logic is already generic
    as it operates on a timer by its ID.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, **kwargs): # task_type is ignored but present in URL
        timer_id = request.data.get("timer_id")
        try:
            timer = Timer.objects.select_related('user__profile').get(id=timer_id)

            # Check if this is a fault-related timer that cannot be manually stopped
            if not timer.can_be_stopped_by_user:
                return Response({
                    "detail": "Cannot manually stop fault-related timer. It will be stopped automatically when the fault is resolved."
                }, status=status.HTTP_403_FORBIDDEN)

            request_user = request.user
            request_profile = request_user.profile
            timer_user = timer.user
            timer_profile = timer_user.profile
            same_team = request_profile.team == timer_profile.team

            # This permission logic is specific but can be generalized later if needed.
            allowed = False
            if request_user.is_admin or timer_user == request_user:
                allowed = True
            elif request_profile.work_location == "office" and (same_team or (timer_profile.team == "machining" and request_profile.team == "manufacturing")):
                allowed = True
            elif getattr(request_profile, "is_lead", False) and same_team:
                allowed = True

            if not allowed:
                return Response({"detail": "Permission denied for this timer."}, status=status.HTTP_403_FORBIDDEN)

            was_running = timer.finish_time is None
            finish_time_from_request = request.data.get("finish_time")

            # Update allowed fields
            for field in ['finish_time', 'comment', 'machine_fk']:
                if field in request.data:
                    setattr(timer, field, request.data[field])

            if was_running and finish_time_from_request:
                timer.stopped_by = request.user

            timer.save()
            return Response({"detail": "Timer stopped and updated."}, status=status.HTTP_200_OK)

        except Timer.DoesNotExist:
            return Response({"detail": "Timer not found."}, status=status.HTTP_404_NOT_FOUND)


class GenericTimerManualEntryView(GenericTimerStartView):
    """
    A generic view for manual timer entry. Inherits from the start view
    and just flips the 'manual_entry' flag.
    """
    def post(self, request, task_type):
        # --- Overlap validation for manual entries ---
        machine_fk_id = request.data.get("machine_fk")
        start_time_str = request.data.get("start_time")
        finish_time_str = request.data.get("finish_time")

        # Only validate if machine and times are provided
        if machine_fk_id and start_time_str and finish_time_str:
            try:
                start_time = _parse_ms(start_time_str)
                finish_time = _parse_ms(finish_time_str)

                # Check for overlapping timers on the same machine.
                # An overlap exists if (StartA < EndB) and (EndA > StartB).
                # We exclude timers where finish_time is null (still running).
                overlapping_timers = Timer.objects.filter(
                    machine_fk_id=machine_fk_id,
                    start_time__lt=finish_time,
                    finish_time__gt=start_time,
                )

                if overlapping_timers.exists():
                    return Response(
                        {"error": "An existing timer for this machine overlaps with the specified time frame."},
                        status=status.HTTP_409_CONFLICT
                    )
            except (ValueError, TypeError):
                return Response({"error": "Invalid timestamp format for start_time or finish_time."}, status=status.HTTP_400_BAD_REQUEST)

        return super().post(request, task_type)


class GenericTimerListView(APIView):
    """
    A generic view to list timers, filterable by a specific task_type.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_type):
        ordering = request.GET.get("ordering", "-finish_time")

        # Map task_type to (app_label, model)
        task_type_map = {
            'machining': ('machining', 'task'),
            'cnc_cutting': ('cnc_cutting', 'cnctask'),
            'operation': ('tasks', 'operation'),
        }

        if task_type not in task_type_map:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        app_label, model_name = task_type_map[task_type]

        try:
            ct = ContentType.objects.get(app_label=app_label, model=model_name)
        except ContentType.DoesNotExist:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        # Include both task-linked timers AND machine-level timers (downtime/break with no operation)
        query = Q(content_type=ct) | Q(content_type__isnull=True)

        if request.GET.get("is_active") == "true":
            query &= Q(finish_time__isnull=True)
        elif request.GET.get("is_active") == "false":
            query &= Q(finish_time__isnull=False)

        user_param = request.GET.get("user")
        # Check if user has admin-like abilities (work_location is 'office')
        if request.user and getattr(request.user, 'profile', None) and request.user.profile.work_location == 'office':
            if user_param:
                query &= Q(user__username=user_param)
        else:
            query &= Q(user=request.user)

        if "issue_key" in request.GET:
            query &= Q(object_id=request.GET["issue_key"])

        if "machine_fk" in request.GET:
            query &= Q(machine_fk=request.GET["machine_fk"])

        start_after = request.GET.get("start_after")
        start_before = request.GET.get("start_before")
        try:
            if start_after:
                ts = int(start_after)
                query &= Q(start_time__gte=ts * 1000 if ts < 1_000_000_000_000 else ts)
            if start_before:
                ts = int(start_before)
                query &= Q(start_time__lte=ts * 1000 if ts < 1_000_000_000_000 else ts)
        except (ValueError, TypeError):
            return Response({"error": "Invalid timestamp"}, status=status.HTTP_400_BAD_REQUEST)

        if "job_no" in request.GET:
            TaskModel = _get_task_model_from_type(task_type)
            if TaskModel and hasattr(TaskModel, 'job_no'):
                task_keys = TaskModel.objects.filter(job_no__icontains=request.GET['job_no']).values_list('key', flat=True)
                query &= Q(object_id__in=list(task_keys))

        # Subquery to calculate total hours for each task
        task_total_hours_subquery = Timer.objects.filter(
            content_type=OuterRef('content_type'),
            object_id=OuterRef('object_id'),
            finish_time__isnull=False
        ).values('content_type', 'object_id').annotate(
            total=Sum(ExpressionWrapper(
                (F('finish_time') - F('start_time')) / 3600000.0,
                output_field=FloatField()
            ))
        ).values('total')

        timers = Timer.objects.prefetch_related('issue_key').annotate(
            duration=ExpressionWrapper(
                (F('finish_time') - F('start_time')) / 3600000.0,
                output_field=FloatField()
            ),
            task_total_hours=Subquery(task_total_hours_subquery)
        ).filter(query).order_by(ordering)

        paginator = CustomPageNumberPagination()
        page = paginator.paginate_queryset(timers, request)
        SerializerClass = get_timer_serializer_class(task_type)
        serializer = SerializerClass(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class GenericTimerDetailView(RetrieveUpdateDestroyAPIView):
    """
    Generic retrieve, update, or delete for a Timer instance.
    Permissions are handled by the calling view.
    """
    queryset = Timer.objects.all()

    def get_serializer_class(self):
        """
        Dynamically determine serializer based on the related task of the timer instance.
        """
        if self.get_object() and self.get_object().content_type:
            return get_timer_serializer_class(self.get_object().content_type.app_label)
        return BaseTimerSerializer

    def get_queryset(self):
        user = self.request.user
        # Admins (office staff) can see all timers
        if user and getattr(user, 'profile', None) and user.profile.work_location == 'office':
            return Timer.objects.all()
        return Timer.objects.filter(user=user)

    def perform_update(self, serializer):
        # Automatically set stopped_by user if a timer is being finished
        if self.request.data.get("finish_time") and not serializer.instance.finish_time:
            serializer.save(stopped_by=self.request.user)
        else:
            serializer.save()

    def destroy(self, request, *args, **kwargs):
        # Only admins (office staff) can delete timers
        if not (request.user and getattr(request.user, 'profile', None) and request.user.profile.work_location == 'office'):
            return Response({"error": "You do not have permission to delete timers."}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class GenericTimerReportView(APIView):
    """
    Generic aggregate reports on timers for a specific task_type.
    """
    permission_classes = [IsAdminUser]

    def get(self, request, task_type):
        group_by = request.query_params.get('group_by', 'user')
        manual_only = request.query_params.get('manual_only') == 'true'
        start_after = request.query_params.get('start_after')
        start_before = request.query_params.get('start_before')

        valid_groups = {'user': 'user__username', 'machine': 'machine_fk', 'job_no': 'object_id', 'issue_key': 'object_id'}
        group_field_name = valid_groups.get(group_by)
        if not group_field_name:
            return Response({'error': 'Invalid group_by value'}, status=status.HTTP_400_BAD_REQUEST)

        # Map task_type to (app_label, model)
        task_type_map = {
            'machining': ('machining', 'task'),
            'cnc_cutting': ('cnc_cutting', 'cnctask'),
            'operation': ('tasks', 'operation'),
        }

        if task_type not in task_type_map:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        app_label, model_name = task_type_map[task_type]

        try:
            ct = ContentType.objects.get(app_label=app_label, model=model_name)
        except ContentType.DoesNotExist:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        timers = Timer.objects.filter(content_type=ct).exclude(finish_time__isnull=True)

        if manual_only:
            timers = timers.filter(manual_entry=True)
        try:
            if start_after:
                timers = timers.filter(start_time__gte=int(start_after))
            if start_before:
                timers = timers.filter(start_time__lte=int(start_before))
        except (ValueError, TypeError):
            return Response({'error': 'Invalid timestamp for start_after/start_before'}, status=status.HTTP_400_BAD_REQUEST)

        duration_expr = ExpressionWrapper((F('finish_time') - F('start_time')) / (1000 * 3600.0), output_field=FloatField())

        report = timers.values(group_field_name).annotate(
            total_hours=Sum(duration_expr),
            avg_duration=Avg(duration_expr),
            timer_count=Count('id'),
            group_val=F(group_field_name),
        ).values('group_val', 'total_hours', 'avg_duration', 'timer_count').order_by('group_val')

        if group_by == 'job_no':
            TaskModel = _get_task_model_from_type(task_type)
            if TaskModel and hasattr(TaskModel, 'job_no'):
                task_keys = [r['group_val'] for r in report]
                tasks = TaskModel.objects.filter(key__in=task_keys).values('key', 'job_no')
                job_no_map = {t['key']: t['job_no'] for t in tasks}

                job_report = defaultdict(lambda: {'total_hours': 0, 'timer_count': 0, 'total_duration_sum': 0})
                for r in report:
                    job_no = job_no_map.get(r['group_val'], 'N/A')
                    job_report[job_no]['total_hours'] += r['total_hours']
                    job_report[job_no]['timer_count'] += r['timer_count']
                    job_report[job_no]['total_duration_sum'] += r['avg_duration'] * r['timer_count']

                final_report = []
                for job_no, data in job_report.items():
                    avg_duration = (data['total_duration_sum'] / data['timer_count']) if data['timer_count'] > 0 else 0
                    final_report.append({'group': job_no, 'total_hours': data['total_hours'], 'avg_duration': avg_duration, 'timer_count': data['timer_count']})
                return Response(sorted(final_report, key=lambda x: x['group'] or ''))

        return Response(report)


class GenericMarkTaskCompletedView(APIView):
    """
    A generic view to mark any task as completed.
    """
    def post(self, request, task_type):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        TaskModel = _get_task_model_from_type(task_type)
        if not TaskModel:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            task = TaskModel.objects.get(key=task_key)
            task.completed_by = request.user
            task.completion_date = int(time.time() * 1000)  # current time in ms

            # Clear planning fields when task is completed (if it has them)
            if hasattr(task, 'in_plan'):
                task.in_plan = False
            if hasattr(task, 'plan_order'):
                task.plan_order = None
            if hasattr(task, 'planned_start_ms'):
                task.planned_start_ms = None
            if hasattr(task, 'planned_end_ms'):
                task.planned_end_ms = None
            if hasattr(task, 'plan_locked'):
                task.plan_locked = False

            task.save()
            return Response({'status': 'Task marked as completed.'})
        except TaskModel.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)


class GenericUnmarkTaskCompletedView(APIView):
    """
    A generic view to unmark any task as completed.
    """
    def post(self, request, task_type):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        TaskModel = _get_task_model_from_type(task_type)
        if not TaskModel:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            task = TaskModel.objects.get(key=task_key)
            task.completed_by = None
            task.completion_date = None
            task.save()
            return Response({'status': 'Task completion removed.'})
        except TaskModel.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)


class GenericPlanningListView(APIView):
    """
    A generic view to list planned and backlog tasks for a specific resource (e.g., a machine).

    Configurable attributes:
    - `task_model`: The task model class (e.g., `machining.Task`).
    - `serializer_class`: The serializer for the response items.
    - `resource_fk_field`: The name of the ForeignKey field on the task model that
      links to the resource (e.g., 'machine_fk').
    """
    task_model = None
    serializer_class = None
    resource_fk_field = None

    # These need to be defined in the child class for filtering to work
    filter_backends = []
    filterset_class = None

    def get(self, request):
        resource_id = request.query_params.get(self.resource_fk_field)
        if not resource_id:
            return Response({"error": f"{self.resource_fk_field} is required"}, status=400)

        only_in_plan = str(request.query_params.get('only_in_plan', 'false')).lower() == 'true'
        t0 = _parse_ms(request.query_params.get('start_after'))
        t1 = _parse_ms(request.query_params.get('start_before'))

        # Base query: active, non-hold, uncompleted tasks for the resource
        qs = self.task_model.objects.select_related(self.resource_fk_field).filter(
                **{f'{self.resource_fk_field}_id': resource_id},
                is_hold_task=False,
                completion_date__isnull=True,
                completed_by__isnull=True
            )

        # Manually apply the filters from the filterset_class
        if self.filterset_class:
            filterset = self.filterset_class(request.query_params, queryset=qs)
            qs = filterset.qs

        # Filter for in-plan tasks and date ranges
        if only_in_plan:
            qs = qs.filter(in_plan=True)
            if t0 is not None and t1 is not None:
                qs = qs.filter(planned_start_ms__lte=t1, planned_end_ms__gte=t0)
        else:
            # Show both in-plan (matching date range) and all backlog tasks
            q_in_plan = Q(in_plan=True)
            if t0 is not None and t1 is not None:
                q_in_plan &= Q(planned_start_ms__lte=t1, planned_end_ms__gte=t0)
            qs = qs.filter(q_in_plan | Q(in_plan=False))

        # Consistent ordering for planning views
        qs = qs.order_by(
            F('in_plan').desc(),
            F('plan_order').asc(nulls_last=True),
            F('planned_start_ms').asc(nulls_last=True),
            F('finish_time').asc(nulls_last=True),
            'key'
        )

        data = self.serializer_class(qs, many=True).data
        return Response(data, status=200)


class GenericProductionPlanView(APIView):
    """
    A generic view for a production plan, annotating tasks with their first timer start.

    Configurable attributes:
    - `task_model`, `serializer_class`, `resource_fk_field`
    """
    task_model = None
    serializer_class = None
    resource_fk_field = None

    def get(self, request):
        from django.db.models import Min

        resource_id = request.query_params.get(self.resource_fk_field)
        if not resource_id:
            return Response({"error": f"{self.resource_fk_field} is required"}, status=400)

        qs = self.task_model.objects.select_related(self.resource_fk_field).prefetch_related('issue_key').annotate(
            first_timer_start=Min('issue_key__start_time')
        ).filter(
            **{f'{self.resource_fk_field}_id': resource_id},
            is_hold_task=False
        )

        qs = qs.order_by(
            F('in_plan').desc(),
            F('plan_order').asc(nulls_last=True),
            F('planned_start_ms').asc(nulls_last=True),
            F('finish_time').asc(nulls_last=True),
            'key'
        )

        data = self.serializer_class(qs, many=True).data
        return Response(data, status=200)


class GenericPlanningBulkSaveView(APIView):
    """
    A generic view to bulk-update planning fields on tasks.

    Configurable attributes:
    - `task_model`: The task model class.
    - `item_serializer_class`: Serializer for validating individual items in the payload.
    - `bulk_list_serializer_class`: List serializer for bulk validation and updates.
    - `response_serializer_class`: Serializer for the success response payload.
    - `resource_fk_field`: The name of the resource ForeignKey field.
    """
    task_model = None
    item_serializer_class = None
    bulk_list_serializer_class = None
    response_serializer_class = None
    resource_fk_field = None

    @transaction.atomic
    def post(self, request):
        items = request.data.get('items', [])
        if not isinstance(items, list) or not items:
            return Response({"error": "Body must include non-empty 'items' array"}, status=400)

        # 1. Item-level validation
        item_ser = self.item_serializer_class(data=items, many=True)
        item_ser.is_valid(raise_exception=True)
        rows = item_ser.validated_data

        # 2. Fetch existing tasks and check for missing keys
        keys = [row['key'] for row in rows]
        existing_qs = self.task_model.objects.select_for_update().filter(key__in=keys)
        inst_map = {t.key: t for t in existing_qs}
        missing = [k for k in keys if k not in inst_map]
        if missing:
            return Response({"error": "Some tasks not found", "keys": missing}, status=400)

        # 3. List-level validation (e.g., resource consistency)
        existing_resource_map = {t.key: getattr(t, self.resource_fk_field) for t in existing_qs}
        raw_by_key = {d['key']: d for d in items if isinstance(d, dict) and 'key' in d}
        raw_rows_in_order = [raw_by_key[k] for k in keys]
        bulk_validate = self.bulk_list_serializer_class(
            child=self.item_serializer_class(),
            data=raw_rows_in_order,
            context={"existing_resource_map": existing_resource_map, "resource_fk_field": self.resource_fk_field},
        )
        bulk_validate.is_valid(raise_exception=True)

        # 4. Pre-flight check for plan_order conflicts (DB and intra-payload)
        intended_map = {}
        for r in rows:
            key = r["key"]
            cur = inst_map[key]
            in_plan = r.get("in_plan", cur.in_plan if hasattr(cur, "in_plan") else True)
            rid_obj = r.get(self.resource_fk_field)
            rid = rid_obj.id if hasattr(rid_obj, "id") else getattr(getattr(cur, self.resource_fk_field, None), "id", None)
            order = r.get("plan_order", getattr(cur, "plan_order", None))
            intended_map[key] = (rid, order, in_plan)

        # 4a. Intra-payload conflicts
        payload_conflicts, seen = [], {}
        for key, (rid, order, in_plan) in intended_map.items():
            if in_plan and rid is not None and order is not None:
                token = (rid, order)
                if token in seen:
                    payload_conflicts.append({"key": key, self.resource_fk_field: rid, "plan_order": order, "conflicts_with": seen[token]})
                else: seen[token] = key
        if payload_conflicts:
            return Response({"error": "Duplicate plan_order within payload", "conflicts": payload_conflicts}, status=400)

        # 4b. DB conflicts (excluding tasks in this batch)
        targets = [(rid, order) for (rid, order, in_plan) in intended_map.values() if in_plan and rid is not None and order is not None]
        if targets:
            q_pairs = Q()
            for rid, order in targets:
                q_pairs |= (Q(**{f'{self.resource_fk_field}_id': rid}) & Q(plan_order=order))
            
            conflict_qs = self.task_model.objects.filter(Q(in_plan=True) & q_pairs).exclude(key__in=keys)
            if conflict_qs.exists():
                db_conflicts = list(conflict_qs.values("key", f'{self.resource_fk_field}_id', "plan_order"))
                return Response({"error": "plan_order conflicts with existing tasks", "conflicts": db_conflicts}, status=400)

        # 5. Perform the bulk update
        instances_in_order = [inst_map[k] for k in keys]
        bulk_updater = self.bulk_list_serializer_class(child=self.item_serializer_class())
        updated_objs = bulk_updater.update(instances_in_order, rows)

        return Response({"updated": self.response_serializer_class(updated_objs, many=True).data}, status=200)


# ==================== Part-Operation System Views ====================


class PartViewSet(ModelViewSet):
    """ViewSet for Part model"""
    queryset = Part.objects.all()
    serializer_class = PartSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PartFilter
    ordering_fields = ['created_at', 'finish_time', 'key', 'job_no', 'name']
    ordering = ['-created_at']

    def get_queryset(self):
        from django.db.models import Count, Q

        # For list view, use lightweight query with counts
        if self.action == 'list':
            return Part.objects.select_related('created_by', 'completed_by').annotate(
                operation_count=Count('operations'),
                incomplete_operation_count=Count('operations', filter=Q(operations__completion_date__isnull=True))
            )

        # For detail/retrieve, load full operations
        return Part.objects.select_related('created_by', 'completed_by').prefetch_related('operations')

    def get_serializer_class(self):
        if self.action == 'create' or self.action == 'bulk_create':
            return PartWithOperationsSerializer
        elif self.action == 'list':
            return PartListSerializer
        return PartSerializer

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request):
        """
        Bulk create multiple parts with their operations.

        Expected payload:
        [
            {
                "task_key": "TI-001",  // optional, original task key
                "name": "Part name",
                "description": "Part description",
                "job_no": "JOB-123",
                "image_no": "IMG-001",
                "position_no": "POS-001",
                "quantity": 10,
                "material": "Steel",
                "dimensions": "100x50x20",
                "weight_kg": "5.5",
                "operations": [
                    {
                        "name": "Operation 1",
                        "description": "Op description",
                        "order": 1,
                        "machine_fk": 1,
                        "estimated_hours": "2.50",
                        "interchangeable": false,
                        "tools": [1, 2, {"tool": 3, "quantity": 2}]
                    }
                ]
            },
            // ... more parts
        ]

        Returns:
        {
            "created": 5,
            "parts": [created part objects with operations]
        }
        """
        if not isinstance(request.data, list):
            return Response(
                {"error": "Expected a list of parts"},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_parts = []
        errors = []

        with transaction.atomic():
            for idx, part_data in enumerate(request.data):
                serializer = self.get_serializer(data=part_data, context={'request': request})
                if serializer.is_valid():
                    try:
                        part = serializer.save()
                        created_parts.append(part)
                    except Exception as e:
                        errors.append({
                            "index": idx,
                            "error": str(e),
                            "data": part_data
                        })
                else:
                    errors.append({
                        "index": idx,
                        "errors": serializer.errors,
                        "data": part_data
                    })

            if errors:
                # Rollback transaction if any errors
                transaction.set_rollback(True)
                return Response(
                    {
                        "error": "Bulk creation failed",
                        "failures": errors
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Serialize created parts for response
        response_serializer = PartSerializer(created_parts, many=True)

        return Response(
            {
                "created": len(created_parts),
                "parts": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def update_operations(self, request, pk=None):
        """
        Bulk update operations for a part.

        Expected payload:
        {
            "operations": [
                {
                    "key": "PT-001-OP-1",  // existing operation to update
                    "name": "Updated name",
                    "machine_fk": 5,
                    "order": 1,
                    "interchangeable": false,
                    "estimated_hours": "2.50",
                    "tools": [
                        1,  // Simple format: just tool ID (quantity defaults to 1)
                        2,
                        {"tool": 3, "quantity": 2, "notes": "Need 2 clamps"}  // Full format with quantity
                    ]
                },
                {
                    // no key = new operation
                    "name": "New operation",
                    "machine_fk": 3,
                    "order": 2,
                    "interchangeable": false,
                    "estimated_hours": "1.50",
                    "tools": [
                        {"tool": 4, "quantity": 3}  // Need 3 of tool #4
                    ]
                }
            ],
            "delete_operations": ["PT-001-OP-3"]  // keys of operations to delete
        }
        """
        from .models import Operation, OperationTool
        from .serializers import OperationCreateSerializer

        part = self.get_object()
        operations_data = request.data.get('operations', [])
        delete_keys = request.data.get('delete_operations', [])

        with transaction.atomic():
            # 1. Delete operations
            if delete_keys:
                operations_to_delete = Operation.objects.filter(
                    part=part,
                    key__in=delete_keys
                )

                # Validate: don't delete operations with timers
                for op in operations_to_delete:
                    if op.timers.exists():
                        return Response({
                            'error': f'Cannot delete operation {op.key} - it has associated timers'
                        }, status=400)

                operations_to_delete.delete()

            # 2. Update or create operations
            for op_data in operations_data:
                tools_data = op_data.pop('tools', [])
                op_key = op_data.pop('key', None)

                if op_key:
                    # Update existing operation
                    try:
                        operation = Operation.objects.get(key=op_key, part=part)

                        # Update fields
                        for field, value in op_data.items():
                            # Handle ForeignKey fields - use field_id for direct ID assignment
                            if field == 'machine_fk' and value is not None:
                                setattr(operation, 'machine_fk_id', value)
                            else:
                                setattr(operation, field, value)
                        operation.save()

                        # Update tools
                        OperationTool.objects.filter(operation=operation).delete()
                        for idx, tool_data in enumerate(tools_data, start=1):
                            # Support both formats: integer (tool ID) or dict (tool ID + quantity)
                            if isinstance(tool_data, dict):
                                tool_id = tool_data.get('tool') or tool_data.get('id')
                                quantity = tool_data.get('quantity', 1)
                                notes = tool_data.get('notes', '')
                            else:
                                tool_id = tool_data
                                quantity = 1
                                notes = ''

                            OperationTool.objects.create(
                                operation=operation,
                                tool_id=tool_id,
                                quantity=quantity,
                                notes=notes,
                                display_order=idx
                            )
                    except Operation.DoesNotExist:
                        return Response({
                            'error': f'Operation {op_key} not found'
                        }, status=404)
                else:
                    # Create new operation
                    serializer = OperationCreateSerializer(data=op_data)
                    if not serializer.is_valid():
                        return Response(serializer.errors, status=400)

                    operation = Operation.objects.create(
                        part=part,
                        created_by=request.user,
                        created_at=int(time.time() * 1000),
                        **serializer.validated_data
                    )

                    # Attach tools
                    for idx, tool_data in enumerate(tools_data, start=1):
                        # Support both formats: integer (tool ID) or dict (tool ID + quantity)
                        if isinstance(tool_data, dict):
                            tool_id = tool_data.get('tool') or tool_data.get('id')
                            quantity = tool_data.get('quantity', 1)
                            notes = tool_data.get('notes', '')
                        else:
                            tool_id = tool_data
                            quantity = 1
                            notes = ''

                        OperationTool.objects.create(
                            operation=operation,
                            tool_id=tool_id,
                            quantity=quantity,
                            notes=notes,
                            display_order=idx
                        )

        # Return updated part with operations
        part.refresh_from_db()
        return Response(self.get_serializer(part).data)


class PartStatsView(APIView):
    """
    GET /tasks/parts/stats/

    Returns aggregate statistics for incomplete parts and operations.
    Only counts incomplete operations (completion_date is NULL) for actionable metrics.
    Ultra-efficient single-query endpoint using database-level aggregations.

    Response:
    {
        "parts_with_unassigned_operations": 15,      // Parts with incomplete ops missing machine
        "parts_with_unplanned_operations": 42,        // Parts with incomplete ops not in plan
        "parts_without_operations": 8,                // Parts with no operations at all
        "incomplete_parts": 65,                       // Parts with at least one incomplete operation
        "total_parts": 150,                           // All parts
        "total_operations": 387,                      // All operations
        "incomplete_operations": 123                  // Incomplete operations
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Count, Q

        # Base filter for incomplete operations
        incomplete_op = Q(operations__completion_date__isnull=True)

        # Single query with conditional aggregations
        stats = Part.objects.aggregate(
            # Parts that have at least one INCOMPLETE operation without a machine
            parts_with_unassigned_operations=Count(
                'key',
                filter=incomplete_op & Q(operations__machine_fk__isnull=True),
                distinct=True
            ),
            # Parts that have at least one INCOMPLETE operation not in plan
            parts_with_unplanned_operations=Count(
                'key',
                filter=incomplete_op & (Q(operations__in_plan=False) | Q(operations__in_plan__isnull=True)),
                distinct=True
            ),
            # Parts without any operations
            parts_without_operations=Count(
                'key',
                filter=Q(operations__isnull=True)
            ),
            # Parts with at least one incomplete operation
            incomplete_parts=Count(
                'key',
                filter=incomplete_op,
                distinct=True
            ),
            # Total counts
            total_parts=Count('key', distinct=True)
        )

        # Get operation counts (separate simple queries)
        stats['total_operations'] = Operation.objects.count()
        stats['incomplete_operations'] = Operation.objects.filter(completion_date__isnull=True).count()

        return Response(stats)


class OperationViewSet(ModelViewSet):
    """
    ViewSet for Operation model with role-based serializers.

    Query parameter 'view' controls serializer:
    - view=operator: Minimal data for operators (OperationOperatorSerializer)
    - view=detail or default: Full data for engineers (OperationDetailSerializer)

    Examples:
    - GET /api/operations/?view=operator  (for operator page)
    - GET /api/operations/?view=detail    (for engineer page)
    - GET /api/operations/PT-001-OP-1/?view=operator
    """
    queryset = Operation.objects.all()
    serializer_class = OperationDetailSerializer  # Default for engineers
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = OperationFilter
    ordering_fields = ['part', 'order', 'created_at', 'plan_order']
    ordering = ['part', 'order']

    def get_serializer_class(self):
        """
        Return different serializers based on 'view' query parameter.
        """
        view_type = self.request.query_params.get('view', 'detail')

        if view_type == 'operator':
            return OperationOperatorSerializer

        # For planning bulk save, use the planning serializer
        if self.action == 'bulk_save_planning':
            return OperationPlanUpdateItemSerializer

        # Default: detailed view for engineers
        return OperationDetailSerializer

    def get_queryset(self):
        queryset = Operation.objects.select_related(
            'part', 'machine_fk', 'created_by', 'completed_by'
        ).prefetch_related(
            'operation_tools__tool',
            'timers'  # Prefetch timers for has_active_timer check
        )

        # Filter by part
        part_key = self.request.query_params.get('part_key')
        if part_key:
            queryset = queryset.filter(part__key=part_key)

        # Filter by machine
        machine_id = self.request.query_params.get('machine_id')
        if machine_id:
            queryset = queryset.filter(machine_fk_id=machine_id)

        # For operator view in list mode: exclude operations with active timers
        view_type = self.request.query_params.get('view', 'detail')
        if view_type == 'operator' and self.action == 'list':
            # Exclude operations that have active timers (finish_time = NULL)
            # Use Count to check if there are active timers
            queryset = queryset.annotate(
                active_timer_count=Count('timers', filter=Q(timers__finish_time__isnull=True))
            ).filter(active_timer_count=0)

        # Annotate hours spent
        queryset = queryset.annotate(
            total_hours_spent=Coalesce(
                ExpressionWrapper(
                    Sum('timers__finish_time', filter=Q(timers__finish_time__isnull=False)) -
                    Sum('timers__start_time', filter=Q(timers__finish_time__isnull=False)),
                    output_field=FloatField()
                ) / 3600000.0,
                Value(0.0)
            )
        )

        return queryset

    @action(detail=True, methods=['post'])
    def mark_completed(self, request, pk=None):
        """Mark operation as completed"""
        operation = self.get_object()

        if operation.completion_date:
            return Response({'error': 'Already completed'}, status=400)

        # Validate order - non-interchangeable operations must wait for ALL previous operations
        if not operation.interchangeable:
            previous_incomplete = Operation.objects.filter(
                part=operation.part,
                order__lt=operation.order,
                completion_date__isnull=True
            )
            if previous_incomplete.exists():
                incomplete_orders = list(previous_incomplete.values_list('order', flat=True))
                return Response({
                    'error': f'Cannot complete operation {operation.order}. All previous operations must be completed first.',
                    'incomplete_operations': incomplete_orders
                }, status=400)

        import time
        operation.completion_date = int(time.time() * 1000)
        operation.completed_by = request.user

        # Clear planning fields when operation is completed
        operation.in_plan = False
        operation.plan_order = None
        operation.planned_start_ms = None
        operation.planned_end_ms = None
        operation.plan_locked = False

        operation.save()

        return Response(self.get_serializer(operation).data)

    @action(detail=True, methods=['post'])
    def unmark_completed(self, request, pk=None):
        """Unmark operation completion and uncomplete parent part if needed"""
        operation = self.get_object()

        # Clear operation completion
        operation.completion_date = None
        operation.completed_by = None
        operation.save()

        # Uncomplete parent part since it now has an incomplete operation
        if operation.part.completion_date:
            operation.part.completion_date = None
            operation.part.completed_by = None
            operation.part.save()

        return Response(self.get_serializer(operation).data)

    @action(detail=True, methods=['post'], url_path='start-timer')
    def start_timer(self, request, pk=None):
        """Start a timer on this operation"""
        operation = self.get_object()

        # Check if already completed
        if operation.completion_date:
            return Response({'error': 'Operation already completed'}, status=400)

        # Check if there's already an active timer
        active_timer = Timer.objects.filter(
            content_type=ContentType.objects.get_for_model(Operation),
            object_id=operation.key,
            finish_time__isnull=True
        ).first()

        if active_timer:
            return Response({'error': 'Timer already running on this operation'}, status=400)

        # Validate operation order - non-interchangeable operations must wait
        if not operation.interchangeable:
            previous_incomplete = Operation.objects.filter(
                part=operation.part,
                order__lt=operation.order,
                completion_date__isnull=True
            )
            if previous_incomplete.exists():
                incomplete_orders = list(previous_incomplete.values_list('order', flat=True))
                return Response({
                    'error': f"Cannot start timer on operation {operation.order}. All previous operations must be completed first.",
                    'incomplete_operations': incomplete_orders
                }, status=400)

        # Validate tool availability
        for op_tool in operation.operation_tools.all():
            tool = op_tool.tool
            if not tool.is_available(op_tool.quantity):
                available = tool.get_available_quantity()
                return Response({
                    'error': f"Tool {tool.code} ({tool.name}) not available",
                    'tool_code': tool.code,
                    'required': op_tool.quantity,
                    'available': available
                }, status=400)

        # Create timer
        timer = Timer.objects.create(
            user=request.user,
            start_time=int(time.time() * 1000),
            content_type=ContentType.objects.get_for_model(Operation),
            object_id=operation.key,
            machine_fk=operation.machine_fk
        )

        return Response({'timer_id': timer.id}, status=201)

    @action(detail=True, methods=['post'], url_path='stop-timer')
    def stop_timer(self, request, pk=None):
        """Stop the active timer on this operation"""
        operation = self.get_object()

        # Find active timer
        active_timer = Timer.objects.filter(
            content_type=ContentType.objects.get_for_model(Operation),
            object_id=operation.key,
            finish_time__isnull=True,
            user=request.user
        ).first()

        if not active_timer:
            return Response({'error': 'No active timer found for this operation'}, status=404)

        # Stop timer
        active_timer.finish_time = int(time.time() * 1000)
        active_timer.stopped_by = request.user
        active_timer.save()

        return Response({'timer_id': active_timer.id}, status=200)

    @action(detail=False, methods=['put'], url_path='planning/bulk-save')
    def bulk_save_planning(self, request):
        """
        Bulk update operation planning.

        Expected payload:
        [
            {
                "key": "PT-001-OP-1",
                "name": "Operation name (optional)",
                "machine_fk": 1,
                "planned_start_ms": 1704067200000,
                "planned_end_ms": 1704153600000,
                "plan_order": 1,
                "plan_locked": false,
                "in_plan": true
            },
            ...
        ]

        Returns: Updated operations
        """
        if not isinstance(request.data, list):
            return Response(
                {"error": "Expected a list of operations"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Extract keys and fetch instances
        keys = [item.get('key') for item in request.data if item.get('key')]
        if not keys:
            return Response(
                {"error": "No operation keys provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch all operations by key
        operations = list(Operation.objects.filter(key__in=keys))
        found_keys = {op.key for op in operations}
        missing_keys = set(keys) - found_keys

        if missing_keys:
            return Response(
                {"error": f"Operations not found: {', '.join(missing_keys)}"},
                status=status.HTTP_404_NOT_FOUND
            )

        # Build existing machine map for validation
        existing_machine_map = {op.key: op.machine_fk_id for op in operations}

        # Use the bulk serializer
        serializer = OperationPlanUpdateItemSerializer(
            operations,
            data=request.data,
            many=True,
            partial=True,
            context={'existing_machine_map': existing_machine_map}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ToolViewSet(ModelViewSet):
    """ViewSet for Tool model"""
    queryset = Tool.objects.filter(is_active=True)
    serializer_class = ToolSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['category', 'is_active']
    ordering_fields = ['code', 'name', 'category']
    ordering = ['code']

    def get_permissions(self):
        # Read-only for all authenticated, write for admins
        if self.action in ['list', 'retrieve']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    @action(detail=False, methods=['get'])
    def available(self, request):
        """Get only tools that have available quantity > 0"""
        tools = self.filter_queryset(self.get_queryset())

        # Filter for available tools
        available_tools = []
        for tool in tools:
            if tool.get_available_quantity() > 0:
                available_tools.append(tool)

        serializer = self.get_serializer(available_tools, many=True)
        return Response(serializer.data)


# ==================== Downtime Tracking Views ====================


class DowntimeReasonListView(APIView):
    """
    GET /tasks/downtime-reasons/

    Returns list of all active downtime reasons for operators to select from when stopping timers.
    Ordered by display_order for optimal UI presentation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .models import DowntimeReason
        from .serializers import DowntimeReasonSerializer

        reasons = DowntimeReason.objects.filter(is_active=True).order_by('display_order', 'name')
        serializer = DowntimeReasonSerializer(reasons, many=True)
        return Response(serializer.data)


class LogReasonView(APIView):
    """
    POST /tasks/log-reason/

    Unified endpoint for logging downtime/break reasons.
    Handles both scenarios:
    1. User has active timer and wants to stop it with a reason
    2. User has no active timer but wants to log a reason (e.g., machine fault when not working)

    Workflow:
    - If current_timer_id provided and user can stop it: stop that timer
    - MACHINE_FAULT: creates fault ticket, sends notification, creates fault-linked downtime timer (cannot be manually stopped)
    - WORK_COMPLETE: marks operation as complete, does not create new timer
    - If reason.creates_timer: start new timer (break/downtime) and return full timer object
    - Fault-related timers (related_fault_id != None) cannot be manually stopped

    Request body:
    {
        "current_timer_id": 123,           # Optional - timer to stop
        "reason_id": 4,                    # Required - DowntimeReason ID
        "comment": "Waiting for steel",    # Optional - description
        "machine_id": 5                    # Required for logging reason without timer
    }

    Note: Downtime/break timers are tracked at the machine level only (not operation-specific).
    This allows tracking general usage of reasons by machine and by user.

    Response:
    {
        "stopped_timer_id": 123,           # ID of stopped timer (if applicable)
        "new_timer_id": 124,               # ID of new timer (if created)
        "timer": {...},                    # Full timer object (if created)
        "fault_id": 45,                    # ID of created fault (if applicable)
        "operation_completed": true,       # If operation marked complete
        "message": "Timer stopped and downtime timer started"
    }
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        from .models import DowntimeReason, Timer
        from machines.models import Machine, MachineFault
        from django.utils import timezone

        # Parse request data
        current_timer_id = request.data.get('current_timer_id')
        reason_id = request.data.get('reason_id')
        comment = request.data.get('comment', '').strip()
        machine_id = request.data.get('machine_id')

        # Validate required fields
        if not reason_id:
            return Response({'error': 'reason_id is required'}, status=400)

        # Get the reason
        try:
            reason = DowntimeReason.objects.get(id=reason_id, is_active=True)
        except DowntimeReason.DoesNotExist:
            return Response({'error': 'Invalid or inactive downtime reason'}, status=400)

        now_ms = int(timezone.now().timestamp() * 1000)
        response_data = {
            'stopped_timer_id': None,
            'new_timer_id': None,
            'fault_id': None,
            'message': ''
        }

        current_timer = None
        machine = None

        # Step 1: Handle stopping current timer if provided
        if current_timer_id:
            try:
                current_timer = Timer.objects.select_related('machine_fk', 'user').get(id=current_timer_id)

                # Check if user can stop this timer
                if not current_timer.can_be_stopped_by_user:
                    return Response({
                        'error': 'Cannot manually stop fault-related timer. It will be stopped automatically when the fault is resolved.'
                    }, status=403)

                # Check permissions (same logic as GenericTimerStopView)
                request_user = request.user
                request_profile = request_user.profile
                timer_user = current_timer.user
                timer_profile = timer_user.profile
                same_team = request_profile.team == timer_profile.team

                allowed = False
                if request_user.is_admin or timer_user == request_user:
                    allowed = True
                elif request_profile.work_location == "office" and (same_team or (timer_profile.team == "machining" and request_profile.team == "manufacturing")):
                    allowed = True
                elif getattr(request_profile, "is_lead", False) and same_team:
                    allowed = True

                if not allowed:
                    return Response({'error': 'Permission denied to stop this timer'}, status=403)

                # Stop the timer
                current_timer.finish_time = now_ms
                current_timer.stopped_by = request_user
                if comment:
                    current_timer.comment = comment
                current_timer.save(update_fields=['finish_time', 'stopped_by', 'comment'])

                response_data['stopped_timer_id'] = current_timer.id
                machine = current_timer.machine_fk

            except Timer.DoesNotExist:
                return Response({'error': 'Timer not found'}, status=404)

        # Step 2: If no current timer, validate machine is provided
        # Note: Downtime/break timers are machine-level only, not operation-specific
        if not current_timer:
            if not machine_id:
                return Response({'error': 'machine_id is required when no current_timer_id is provided'}, status=400)

            try:
                machine = Machine.objects.get(id=machine_id)
            except Machine.DoesNotExist:
                return Response({'error': 'Machine not found'}, status=404)

        # If we don't have a machine at this point, something is wrong
        if not machine:
            return Response({'error': 'Machine is required for all timer operations'}, status=400)

        # Check for existing active timer on this machine (only if we're going to create a new timer)
        # Skip this check if we just stopped a timer (current_timer was provided and stopped)
        if reason.creates_timer and not current_timer:
            existing_active_timer = Timer.objects.filter(
                machine_fk=machine,
                finish_time__isnull=True
            ).first()
            if existing_active_timer:
                return Response({
                    'error': 'There is already an active timer on this machine. Stop it first before starting a new one.',
                    'existing_timer_id': existing_active_timer.id,
                    'existing_timer_user': existing_active_timer.user.username
                }, status=409)

        # Step 3: Handle MACHINE_FAULT reason - create fault and auto-stop productive timers
        fault = None
        if reason.code == 'MACHINE_FAULT':
            if not machine:
                return Response({'error': 'Machine is required for machine fault reasons'}, status=400)

            fault_description = comment or 'Arıza bildirildi'
            fault = MachineFault.objects.create(
                machine=machine,
                reported_by=request.user,
                description=fault_description,
                is_breaking=True,
                downtime_start_ms=now_ms
            )
            response_data['fault_id'] = fault.id

            # Send Telegram notification
            self._send_telegram_notification(fault, request.user)

            # If there was an active productive timer that we stopped, link it to the fault
            # and create a downtime timer linked to the fault
            if current_timer and current_timer.timer_type == 'productive':
                # We already stopped the productive timer in Step 1
                # Now create downtime timer linked to the fault (machine-level only)
                new_timer = Timer.objects.create(
                    user=request.user,
                    start_time=now_ms,
                    machine_fk=machine,
                    timer_type='downtime',
                    downtime_reason=reason,
                    related_fault=fault,
                    comment=comment or f'Arıza nedeniyle duruş: {fault_description}'
                )
                response_data['new_timer_id'] = new_timer.id
                response_data['timer'] = self._serialize_timer(new_timer)
                return Response(response_data, status=200)

            # If no active timer, still create downtime timer for the machine
            # This handles the case where user reports fault when not actively working
            elif not current_timer:
                new_timer = Timer.objects.create(
                    user=request.user,
                    start_time=now_ms,
                    machine_fk=machine,
                    timer_type='downtime',
                    downtime_reason=reason,
                    related_fault=fault,
                    comment=comment or f'Arıza bildirildi: {fault_description}'
                )
                response_data['new_timer_id'] = new_timer.id
                response_data['timer'] = self._serialize_timer(new_timer)
                response_data['message'] = f"Machine fault reported and downtime timer started"
                return Response(response_data, status=200)

        # Step 4: Create new timer if reason requires it (and not already handled above)
        # Note: Downtime/break timers are machine-level only, not operation-specific
        if reason.creates_timer:
            # Determine timer type based on reason category
            timer_type = 'break' if reason.category == 'break' else 'downtime'

            new_timer = Timer.objects.create(
                user=request.user,
                start_time=now_ms,
                machine_fk=machine,
                timer_type=timer_type,
                downtime_reason=reason,
                related_fault=fault,
                comment=comment or None
            )
            response_data['new_timer_id'] = new_timer.id
            response_data['timer'] = self._serialize_timer(new_timer)

        # Step 6: Build response message
        if current_timer and response_data['new_timer_id']:
            response_data['message'] = f"Timer stopped and {reason.name} timer started"
        elif current_timer:
            response_data['message'] = f"Timer stopped: {reason.name}"
        elif response_data['new_timer_id']:
            response_data['message'] = f"{reason.name} timer started"
        elif response_data['fault_id']:
            response_data['message'] = f"Machine fault reported: {reason.name}"
        else:
            response_data['message'] = f"Reason logged: {reason.name}"

        return Response(response_data, status=200)

    def _serialize_timer(self, timer):
        """Serialize a timer object to return in API response"""
        from .serializers import BaseTimerSerializer
        serializer = BaseTimerSerializer(timer)
        return serializer.data

    def _send_telegram_notification(self, fault, user):
        """Send Telegram notification when a machine fault is reported"""
        from config.settings import TELEGRAM_MAINTENANCE_BOT_TOKEN
        import requests

        if not TELEGRAM_MAINTENANCE_BOT_TOKEN:
            return  # quietly skip if token not configured

        CHAT_ID = "-4944950975"  # your group/chat

        machine_name = fault.machine.name if fault.machine else (fault.asset_name or "Bilinmiyor")
        description = fault.description or "Yok"
        talep_eden = user.get_full_name() or user.username

        message = (
            "🛠 *Yeni Bakım Talebi*\n"
            f"👤 *Talep Eden:* {talep_eden}\n"
            f"🖥 *Makine:* {machine_name}\n"
            f"📄 *Açıklama:* {description}\n"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, data=payload, timeout=5)
        except requests.RequestException as e:
            print("Telegram bildirim hatası:", e)