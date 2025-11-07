from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from django.db.models import Q, F, ExpressionWrapper, FloatField, Sum, Avg, Count
from django.contrib.contenttypes.models import ContentType
from collections import defaultdict
from django.db import transaction
import time

# Create your views here.
from .models import Timer
from .serializers import BaseTimerSerializer
from config.pagination import CustomPageNumberPagination


def _get_task_model_from_type(task_type):
    if task_type == 'machining':
        from machining.models import Task
        return Task
    # Add other task types here
    elif task_type == 'cnc_cutting':
        from cnc_cutting.models import CncTask
        return CncTask
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

        SerializerClass = get_timer_serializer_class(task_type)
        serializer = SerializerClass(data=data, context={'request': request})
        if serializer.is_valid():
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

        try:
            ct = ContentType.objects.get(app_label=task_type, model='task' if task_type == 'machining' else 'cnctask')
        except ContentType.DoesNotExist:
            return Response({"error": f"Invalid task_type '{task_type}'"}, status=status.HTTP_400_BAD_REQUEST)

        query = Q(content_type=ct)

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

        timers = Timer.objects.prefetch_related('issue_key').annotate(
            duration=ExpressionWrapper(
                (F('finish_time') - F('start_time')) / 3600000.0,
                output_field=FloatField()
            )
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

        try:
            ct = ContentType.objects.get(app_label=task_type, model='task' if task_type == 'machining' else 'cnctask')
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