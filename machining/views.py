import time
from rest_framework.response import Response
from django.db.models import F, Sum, ExpressionWrapper, FloatField
from machining.filters import TaskFilter
from machining.permissions import MachiningProtectedView
from users.permissions import IsAdmin, IsMachiningUserOrAdmin
from .models import Task, TaskKeyCounter, Timer
from .serializers import HoldTaskSerializer, PlanningListItemSerializer, TaskPlanUpdateItemSerializer, TaskSerializer, TimerSerializer
from django.db.models import Q, Count, Avg
from rest_framework.views import APIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.viewsets import ModelViewSet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from config.pagination import CustomPageNumberPagination  # ✅ Use your custom paginator
from rest_framework.filters import OrderingFilter
from django.db import transaction
from rest_framework import permissions, status, views
from .serializers import MachineTimelineSegmentSerializer
from .services.timeline import build_machine_timeline  # _parse_ms is small; OK to re-use
from rest_framework import status

class TimerStartView(MachiningProtectedView):
    def post(self, request):
        data = request.data.copy()
        data["manual_entry"] = False
        serializer = TimerSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            timer = serializer.save()
            return Response({"id": timer.id}, status=200)
        return Response(serializer.errors, status=400)

# API View for maintenance to be able to stop maintenance timers.
class TimerStopView(APIView):
    def post(self, request):
        timer_id = request.data.get("timer_id")
        try:
            timer = Timer.objects.get(id=timer_id)
            request_user = request.user
            request_profile = request_user.profile
            timer_user = timer.user
            timer_profile = timer_user.profile
            same_team = request_profile.team == timer_profile.team

            # Default deny
            allowed = False

            if request_user.is_admin or timer_user == request_user:
                allowed = True
            elif request_profile.work_location == "office" and (same_team or (timer_profile.team == "machining" and request_profile.team == "manufacturing")):
                allowed = True
            elif getattr(request_profile, "is_lead", False) and same_team:
                allowed = True

            if not allowed:
                return Response("Permission denied for this timer.", status=403)

            was_running = timer.finish_time is None
            finish_time_from_request = request.data.get("finish_time")

            # Update allowed fields
            for field in ['finish_time', 'comment', 'machine']:
                if field in request.data:
                    setattr(timer, field, request.data[field])

            # ✅ Automatically set stopped_by
            if was_running and finish_time_from_request:
                timer.stopped_by = request.user

            timer.save()
            return Response("Timer stopped and updated.", status=200)

        except Timer.DoesNotExist:
            return Response("Timer not found.", status=404)


class TimerManualEntryView(MachiningProtectedView):
    def post(self, request):
        data = request.data.copy()
        data["manual_entry"] = True
        serializer = TimerSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            timer = serializer.save()
            return Response({"id": timer.id}, status=200)
        return Response(serializer.errors, status=400)

class TimerListView(MachiningProtectedView):
    def get(self, request):
        ordering = request.GET.get("ordering", "-finish_time")

        query = Q()

        if request.GET.get("is_active") == "true":
            query &= Q(finish_time__isnull=True)
        elif request.GET.get("is_active") == "false":
            query &= Q(finish_time__isnull=False)

        user_param = request.GET.get("user")

        if request.user and request.user.is_admin:
            if user_param:
                query &= Q(user__username=user_param)
        else:
            query &= Q(user=request.user)

        if "issue_key" in request.GET:
            query &= Q(issue_key=request.GET["issue_key"])

        if "machine_fk" in request.GET:
            query &= Q(machine_fk=request.GET["machine_fk"])

        start_after = request.GET.get("start_after")
        start_before = request.GET.get("start_before")
        try:
            if start_after:
                ts = int(start_after)
                if ts < 1_000_000_000_000:
                    ts *= 1000
                query &= Q(start_time__gte=ts)
            if start_before:
                ts = int(start_before)
                if ts < 1_000_000_000_000:
                    ts *= 1000
                query &= Q(start_time__lte=ts)
        except ValueError:
            return Response({"error": "Invalid timestamp"}, status=400)

        if "job_no" in request.GET:
            query &= Q(issue_key__job_no=request.GET["job_no"])

        timers = Timer.objects.annotate(
                    duration=ExpressionWrapper(
                        (F('finish_time') - F('start_time')) / 3600000.0,
                        output_field=FloatField()
                    )
                ).filter(query).order_by(ordering)
        paginator = CustomPageNumberPagination()  # ✅ use your custom paginator
        page = paginator.paginate_queryset(timers, request)
        serializer = TimerSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class TimerDetailView(RetrieveUpdateDestroyAPIView):
    queryset = Timer.objects.all()
    serializer_class = TimerSerializer
    permission_classes = [IsMachiningUserOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Timer.objects.all()
        return Timer.objects.filter(user=user)

    def perform_update(self, serializer):
        serializer.save(stopped_by=self.request.user if self.request.data.get("finish_time") else serializer.instance.stopped_by)

    def destroy(self, request, *args, **kwargs):
        user = request.user

        if not user.is_admin:
            return Response({"error": "You are not allowed to delete this timer."}, status=403)

        return super().destroy(request, *args, **kwargs)


class TimerReportView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        # Optional query params
        group_by = request.query_params.get('group_by', 'user')  # user, machine, job_no
        manual_only = request.query_params.get('manual_only') == 'true'
        start_after = request.query_params.get('start_after')
        start_before = request.query_params.get('start_before')

        # Valid group_by fields
        valid_groups = {
            'user': 'user__username',
            'machine': 'machine_fk',
            'job_no': 'issue_key__job_no',
            'issue_key': 'issue_key',
        }
        group_field = valid_groups.get(group_by)
        if not group_field:
            return Response({'error': 'Invalid group_by value'}, status=400)

        # Base queryset
        timers = Timer.objects.all()

        # Filters
        if manual_only:
            timers = timers.filter(manual_entry=True)
        if start_after:
            try:
                start_after_ts = int(start_after)
                timers = timers.filter(start_time__gte=start_after_ts)
            except ValueError:
                return Response({'error': 'start_after must be a timestamp'}, status=400)
        if start_before:
            try:
                start_before_ts = int(start_before)
                timers = timers.filter(start_time__lte=start_before_ts)
            except ValueError:
                return Response({'error': 'start_before must be a timestamp'}, status=400)

        # Only consider timers that are stopped
        timers = timers.exclude(finish_time__isnull=True)

        # Calculate duration (seconds), convert to hours
        duration_expr = ExpressionWrapper(
            (F('finish_time') - F('start_time')) / (1000 * 3600.0),
            output_field=FloatField()
        )

        report = (
            timers
            .values(group_field)
            .annotate(
                total_hours=Sum(duration_expr),
                avg_duration=Avg(duration_expr),
                timer_count=Count('id'),
                group=F(group_field),
            )
            .values('group', 'total_hours', 'avg_duration', 'timer_count')
            .order_by('group')
        )

        return Response(report)
    


class TaskViewSet(ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    permission_classes = [IsMachiningUserOrAdmin]
    filterset_class = TaskFilter
    pagination_class = CustomPageNumberPagination
    ordering_fields = ['key', 'job_no', 'image_no', 'position_no', 'completion_date', 'created_at', 'total_hours_spent', 'estimated_hours', 'finish_time']  # Add any fields you want to allow
    ordering = ['-completion_date']  # Default ordering

    def get_queryset(self):
        return Task.objects.filter(is_hold_task=False).prefetch_related('timers')
    
class TaskBulkCreateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        tasks_data = request.data
        if not isinstance(tasks_data, list):
            return Response({'error': 'Expected a list of tasks'}, status=400)

        tasks_to_create = [task for task in tasks_data if not task.get('key')]

        with transaction.atomic():
            counter = TaskKeyCounter.objects.select_for_update().get(prefix="TI")
            start = counter.current + 1
            counter.current += len(tasks_to_create)
            counter.save()

            i = 0
            for task in tasks_data:
                if not task.get('key'):
                    task['key'] = f"TI-{start + i:03d}"
                    i += 1

        serializer = TaskSerializer(data=tasks_data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=201)
    

class HoldTaskViewSet(ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = HoldTaskSerializer
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_class = TaskFilter

    def get_queryset(self):
        return Task.objects.filter(is_hold_task=True)


class MarkTaskCompletedView(APIView):
    permission_classes = [IsMachiningUserOrAdmin]

    def post(self, request):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=400)

        try:
            task = Task.objects.get(key=task_key)
            task.completed_by = request.user
            task.completion_date = int(time.time() * 1000)  # current time in ms
            task.save()
            return Response({'status': 'Task marked as completed.'})
        except Task.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=404)

class UnmarkTaskCompletedView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=400)

        try:
            task = Task.objects.get(key=task_key)
            task.completed_by = None
            task.completion_date = None
            task.save()
            return Response({'status': 'Task completion removed.'})
        except Task.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=404)
        
class InitTaskKeyCounterView(APIView):
    permission_classes = [IsAdmin]  # 🔒 restrict who can call this

    def post(self, request):
        counter, created = TaskKeyCounter.objects.get_or_create(prefix="TI", defaults={"current": 0})
        return Response({
            "status": "created" if created else "already_exists",
            "prefix": counter.prefix,
            "current": counter.current
        })

def _parse_ms(val):
    if val is None: return None
    ts = int(val)
    return ts * 1000 if ts < 1_000_000_000_000 else ts

class PlanningListView(APIView):
    """
    GET /machining/planning/list/?machine_fk=5&only_in_plan=false&start_after=<ms|sec>&start_before=<ms|sec>
    - Excludes hold tasks
    - Returns BOTH in-plan and backlog (unless only_in_plan=true)
    - Includes estimated_hours, total_hours_spent, remaining_hours
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        machine_id = request.query_params.get('machine_fk')
        if not machine_id:
            return Response({"error": "machine_fk is required"}, status=400)

        only_in_plan = str(request.query_params.get('only_in_plan', 'false')).lower() == 'true'
        t0 = _parse_ms(request.query_params.get('start_after'))
        t1 = _parse_ms(request.query_params.get('start_before'))

        qs = Task.objects.select_related('machine_fk').filter(
            machine_fk_id=machine_id,
            is_hold_task=False,     # exclude holds from planning
        )

        if only_in_plan:
            qs = qs.filter(in_plan=True)
            if t0 is not None and t1 is not None:
                qs = qs.filter(planned_start_ms__lte=t1, planned_end_ms__gte=t0)
        else:
            q_in_plan = Q(in_plan=True)
            if t0 is not None and t1 is not None:
                q_in_plan &= Q(planned_start_ms__lte=t1, planned_end_ms__gte=t0)
            qs = qs.filter(q_in_plan | Q(in_plan=False))

        qs = qs.order_by(
            F('in_plan').desc(),                        # in-plan first
            F('plan_order').asc(nulls_last=True),
            F('planned_start_ms').asc(nulls_last=True),
            F('finish_time').asc(nulls_last=True),      # backlog seed
            'key'
        )

        data = PlanningListItemSerializer(qs, many=True).data
        return Response(data, status=200)


class PlanningBulkSaveView(APIView):
    """
    POST /machining/planning/bulk-save/
    {
      "items": [
        {"key":"TI-001","machine_fk":5,"planned_start_ms":..., "planned_end_ms":..., "plan_order":1, "plan_locked":true, "in_plan": true},
        {"key":"TI-002","plan_order":2, "in_plan": false}
      ]
    }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    @transaction.atomic
    def post(self, request):
        items = request.data.get('items', [])
        if not isinstance(items, list) or not items:
            return Response({"error": "Body must include non-empty 'items' array"}, status=400)

        # Validate payload
        ser = TaskPlanUpdateItemSerializer(data=items, many=True)
        ser.is_valid(raise_exception=True)

        # Build instance list in the SAME ORDER as validated_data
        keys = [row['key'] for row in ser.validated_data]
        inst_map = {t.key: t for t in Task.objects.select_for_update().filter(key__in=keys)}
        missing = [k for k in keys if k not in inst_map]
        if missing:
            return Response({"error": "Some tasks not found", "keys": missing}, status=400)
        instances = [inst_map[k] for k in keys]

        # Bulk update via the ListSerializer.update we defined
        updated = ser.update(instances, ser.validated_data)

        return Response({"updated": PlanningListItemSerializer(updated, many=True).data}, status=200)
    
class MachineTimelineView(APIView):
    """
    GET /machining/analytics/machine-timeline/?machine_fk=<id>&start_after=<ms|sec>&start_before=<ms|sec>
    Returns:
      {
        "actual":  [ {start_ms,end_ms,task_key,task_name,is_hold,category:"work|hold"} ],
        "idle":    [ {start_ms,end_ms,...,category:"idle"} ],
        "totals":  { productive_seconds, hold_seconds, idle_seconds }
      }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        machine_id = request.query_params.get('machine_fk')
        if not machine_id:
            return Response({"error": "machine_fk is required"}, status=400)

        start_after = _parse_ms(request.query_params.get('start_after'))
        start_before = _parse_ms(request.query_params.get('start_before'))

        payload = build_machine_timeline(int(machine_id), start_after, start_before)
        return Response({
            "actual":  MachineTimelineSegmentSerializer(payload["actual"], many=True).data,
            "idle":    MachineTimelineSegmentSerializer(payload["idle"], many=True).data,
            "totals":  payload["totals"],
        }, status=status.HTTP_200_OK)