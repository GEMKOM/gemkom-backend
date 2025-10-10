import time
from rest_framework.response import Response

from django.db.models import Sum, Max, F, OuterRef, Exists, Q, Case, When, Value, CharField
from django.db.models import F, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce
from machines.models import Machine
from machining.filters import TaskFilter
from machining.permissions import MachiningProtectedView, can_view_all_money, can_view_all_users_hours, can_view_header_totals_only
from tasks.models import Timer, TaskKeyCounter
from machining.services.timers import categorize_timer_segments
from users.permissions import IsAdmin, IsMachiningUserOrAdmin
from .models import JobCostAgg, JobCostAggUser, Task
from .serializers import HoldTaskSerializer, PlanningListItemSerializer, ProductionPlanSerializer, TaskPlanBulkListSerializer, TaskPlanUpdateItemSerializer, TaskSerializer, TimerSerializer
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
from .services.timeline import _build_bulk_machine_timelines, _ensure_valid_range  # _parse_ms is small; OK to re-use
from rest_framework import status
from collections import defaultdict

try:
    from django.contrib.postgres.aggregates import ArrayAgg  # type: ignore
except Exception:  # pragma: no cover
    ArrayAgg = None  # fallback path below

class TimerStartView(MachiningProtectedView):
    def post(self, request):
        data = request.data.copy()
        # The frontend will now send 'task_key' and 'task_type'
        # Our updated serializer handles converting this to a GFK
        if 'issue_key' in data:
            data['task_key'] = data.pop('issue_key')
        # We must specify the task type for the GFK. This endpoint is for machining tasks.
        data['task_type'] = 'machining'
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
            timer = Timer.objects.select_related('user__profile').get(id=timer_id)
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
            for field in ['finish_time', 'comment', 'machine_fk']:
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
        # The frontend will now send 'task_key' and 'task_type'
        # Our updated serializer handles converting this to a GFK
        if 'issue_key' in data:
            data['task_key'] = data.pop('issue_key')
        # We must specify the task type for the GFK. This endpoint is for machining tasks.
        data['task_type'] = 'machining'
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
            # Query the GFK via its object_id
            query &= Q(object_id=request.GET["issue_key"])

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
            # This requires a more complex query across the GFK relationship
            # For now, we assume the frontend filters by task_key directly
            pass

        timers = Timer.objects.prefetch_related('issue_key').annotate(
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
    ordering_fields = ['key', 'job_no', 'image_no', 'position_no', 'completion_date', 'created_at', 'total_hours_spent', 'estimated_hours', 'finish_time', 'plan_order']  # Add any fields you want to allow
    ordering = ['-completion_date']  # Default ordering

    def get_queryset(self):
        # 'issue_key' is the GenericRelation from tasks.Timer back to this Task
        # prefetch_related works seamlessly with it for great performance.
        return Task.objects.filter(is_hold_task=False).prefetch_related('issue_key')
    
class TaskBulkCreateView(APIView):
    permission_classes = [IsAdmin]

    def post(self, request):
        tasks_data = request.data
        if not isinstance(tasks_data, list):
            return Response({'error': 'Expected a list of tasks'}, status=400)

        tasks_to_create = [task for task in tasks_data if not task.get('key')]

        with transaction.atomic():
            # Use the generic TaskKeyCounter from the 'tasks' app
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
        # Use the generic TaskKeyCounter from the 'tasks' app
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
                is_hold_task=False,
                completion_date__isnull=True,
                completed_by__isnull=True

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
            F('in_plan').desc(),
            F('plan_order').asc(nulls_last=True),
            F('planned_start_ms').asc(nulls_last=True),
            F('finish_time').asc(nulls_last=True),
            'key'
        )

        data = PlanningListItemSerializer(qs, many=True).data
        return Response(data, status=200)


class ProductionPlanView(APIView):
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

        # Use the reverse GFK relation 'issue_key'
        from django.db.models import Min
        from tasks.models import Timer as NewTimer

        qs = Task.objects.select_related('machine_fk').prefetch_related('issue_key').annotate(first_timer_start=Min('issue_key__start_time')).filter(
                machine_fk_id=machine_id,
                is_hold_task=False
            )

        qs = qs.order_by(
            F('in_plan').desc(),
            F('plan_order').asc(nulls_last=True),
            F('planned_start_ms').asc(nulls_last=True),
            F('finish_time').asc(nulls_last=True),
            'key'
        )

        data = ProductionPlanSerializer(qs, many=True).data
        return Response(data, status=200)

class PlanningBulkSaveView(APIView):
    """
    POST /machining/planning/bulk-save/
    {
      "items": [
        {"key":"TI-001","in_plan": true,  "machine_fk":5,"planned_start_ms":..., "planned_end_ms":..., "plan_order":1, "plan_locked":true},
        {"key":"TI-002","in_plan": false}
      ]
    }

    Behavior (existing tasks only):
      - in_plan:false -> remove from plan (clear planning fields)
      - in_plan:true  -> add to plan or update plan fields (partial)
      - Missing keys  -> 400 with list of missing
    """
    permission_classes = [IsMachiningUserOrAdmin]

    @transaction.atomic
    def post(self, request):
        items = request.data.get('items', [])
        if not isinstance(items, list) or not items:
            return Response({"error": "Body must include non-empty 'items' array"}, status=400)

        # 1) ITEM-LEVEL VALIDATION (once, on raw payload)
        item_ser = TaskPlanUpdateItemSerializer(data=items, many=True)
        item_ser.is_valid(raise_exception=True)
        rows = item_ser.validated_data  # machine_fk may now be a Machine instance

        # 2) FETCH EXISTING (lock) & fail if any key is missing
        keys = [row['key'] for row in rows]
        existing_qs = Task.objects.select_for_update().filter(key__in=keys)
        inst_map = {t.key: t for t in existing_qs}
        missing = [k for k in keys if k not in inst_map]
        if missing:
            return Response({"error": "Some tasks not found", "keys": missing}, status=400)

        existing_machine_map = {t.key: t.machine_fk for t in existing_qs}

        # 3) LIST-LEVEL PAYLOAD UNIQUENESS (run on raw subset to avoid instance coercion)
        raw_by_key = {d['key']: d for d in items if isinstance(d, dict) and 'key' in d}
        raw_rows_in_order = [raw_by_key[k] for k in keys]
        bulk_validate = TaskPlanBulkListSerializer(
            child=TaskPlanUpdateItemSerializer(),
            data=raw_rows_in_order,
            context={"existing_machine_map": existing_machine_map},
        )
        bulk_validate.is_valid(raise_exception=True)  # only triggers list-level validate()

        # 3b) Optional: DB preflight for intended (machine_fk, plan_order) conflicts (friendlier 400)
        intended_map = {}  # key -> (mid, order, in_plan)
        for r in rows:
            key = r["key"]
            cur = inst_map[key]
            in_plan = r.get("in_plan", cur.in_plan if hasattr(cur, "in_plan") else True)

            # machine_fk may be instance or id or None
            mid = r.get("machine_fk")
            if hasattr(mid, "id"):
                mid = mid.id
            elif mid is None:
                mid = getattr(cur.machine_fk, "id", None)

            order = r.get("plan_order", getattr(cur, "plan_order", None))
            intended_map[key] = (mid, order, in_plan)

        # (b1) Detect intra-payload duplicates (two items target same (mid, order))
        payload_conflicts = []
        seen = {}
        for key, (mid, order, in_plan) in intended_map.items():
            if in_plan and mid is not None and order is not None:
                token = (mid, order)
                if token in seen:
                    payload_conflicts.append({
                        "key": key,
                        "machine_fk": mid,
                        "plan_order": order,
                        "conflicts_with": seen[token],
                        "source": "payload"
                    })
                else:
                    seen[token] = key

        if payload_conflicts:
            return Response(
                {"error": "Duplicate plan_order within payload",
                "conflicts": payload_conflicts},
                status=400
            )

        # (b2) Check DB conflicts for the intended positions, but ignore keys in this batch
        #     (because they will be updated together).
        db_conflicts = []
        batch_keys = set(keys)

        # Gather all (mid, order) pairs we intend to occupy
        targets = [(mid, order) for (mid, order, in_plan) in intended_map.values()
                if in_plan and mid is not None and order is not None]

        # Short-circuit if nothing to check
        if targets:
            # Efficient enough for typical plan sizes; build a combined OR query
            from django.db.models import Q
            q = Q(in_plan=True)
            # OR over all target pairs
            pair_q = Q()
            for mid, order in targets:
                pair_q |= (Q(machine_fk_id=mid) & Q(plan_order=order))
            q &= pair_q

            # Ignore any tasks that are part of this same bulk update
            qs = Task.objects.filter(q).exclude(key__in=batch_keys)

            # If anything remains, those are *real* conflicts
            if qs.exists():
                db_conflicts = list(qs.values("key", "machine_fk_id", "plan_order"))

        if db_conflicts:
            return Response(
                {"error": "plan_order conflicts with existing tasks (outside this payload)",
                "conflicts": db_conflicts},
                status=400
            )
        
        instances_in_order = [inst_map[k] for k in keys]
        bulk_updater = TaskPlanBulkListSerializer(child=TaskPlanUpdateItemSerializer())
        updated_objs = bulk_updater.update(instances_in_order, rows)

        return Response({"updated": PlanningListItemSerializer(updated_objs, many=True).data}, status=200)
    

# views.py
from django.db.models import Q, F, Sum, Max, Count, Value, DecimalField
from django.db.models.functions import Coalesce
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from users.permissions import IsMachiningUserOrAdmin
from machines.models import Machine
from .models import Task


class PlanningAggregateView(APIView):
    """
    GET /machining/planning/aggregate/?machine_fk=<id|all>

    Returns aggregate metrics per machine and overall, without listing tasks.

    Filters included in all aggregations:
      - in_plan = True
      - is_hold_task = False
      - completion_date IS NULL
      - completed_by IS NULL

    Response shape:
    {
      "machines": [
        {
          "machine_id": 5,
          "machine_name": "Doosan DBC130L II",
          "totals": {
            "total_estimated_hours": 42.5,
            "latest_planned_end_ms": 1729000000000,
            "task_count": 9
          },
          "jobs": [
            {
              "job_no": "J-001",
              "total_estimated_hours": 30.5,
              "latest_planned_end_ms": 1728800000000,
              "task_count": 6
            },
            {
              "job_no": null,
              "total_estimated_hours": 12.0,
              "latest_planned_end_ms": 1729000000000,
              "task_count": 3
            }
          ]
        },
        ...
      ],
      "overall_totals": {
        "total_estimated_hours": 60.5,
        "latest_planned_end_ms": 1729000000000,
        "task_count": 13
      }
    }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        # --- Machine selection
        machine_param = request.query_params.get("machine_fk")
        if machine_param and str(machine_param).lower() != "all":
            try:
                machine_ids = [int(machine_param)]
            except (TypeError, ValueError):
                return Response({"error": "machine_fk must be an integer id or 'all'."}, status=400)
            machines = Machine.objects.filter(id__in=machine_ids).only("id", "name")
        else:
            machines = Machine.objects.filter(used_in="machining", is_active=True).only("id", "name", "machine_type")
            machine_ids = list(machines.values_list("id", flat=True))

        machines_by_id = {m.id: m for m in machines}

        # --- Base queryset: active, in-plan, non-hold tasks, not completed
        agg_base = Task.objects.filter(
            machine_fk_id__in=machine_ids,
            in_plan=True,
            is_hold_task=False,
            completion_date__isnull=True,
            completed_by__isnull=True,
        )

        # --- Per-machine totals
        per_machine = (
            agg_base
            .values("machine_fk_id")
            .annotate(
                total_estimated_hours=Coalesce(
                    Sum("estimated_hours"), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
                ),
                latest_planned_end_ms=Max("planned_end_ms"),
                task_count=Count("key", distinct=True),
            )
        )
        per_machine_map = {row["machine_fk_id"]: row for row in per_machine}

        # --- Per-machine, grouped-by-job_no totals
        per_machine_jobs = (
            agg_base
            .values("machine_fk_id", "job_no")
            .annotate(
                total_estimated_hours=Coalesce(
                    Sum("estimated_hours"), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
                ),
                latest_planned_end_ms=Max("planned_end_ms"),
                task_count=Count("key", distinct=True),
            )
            .order_by("machine_fk_id", "job_no")
        )

        # Build {machine_id: [job rows...]}
        jobs_map = {mid: [] for mid in machine_ids}
        for row in per_machine_jobs:
            mid = row["machine_fk_id"]
            jobs_map.setdefault(mid, []).append({
                "job_no": row["job_no"],  # can be None
                "total_estimated_hours": float(row["total_estimated_hours"] or 0),
                "latest_planned_end_ms": row["latest_planned_end_ms"],
                "task_count": int(row["task_count"] or 0),
            })

        # --- Compose response
        items = []
        overall = {
            "total_estimated_hours": 0.0,
            "latest_planned_end_ms": None,
            "task_count": 0,
        }

        for mid in machine_ids:
            m = machines_by_id.get(mid)
            name = getattr(m, "name", None)

            totals_row = per_machine_map.get(mid, {
                "total_estimated_hours": 0,
                "latest_planned_end_ms": None,
                "task_count": 0,
            })

            total_est = float(totals_row["total_estimated_hours"] or 0)
            latest_end = totals_row["latest_planned_end_ms"]
            count = int(totals_row["task_count"] or 0)

            items.append({
                "machine_id": mid,
                "machine_name": name,
                "machine_type_label": m.get_machine_type_display(),
                "totals": {
                    "total_estimated_hours": total_est,
                    "latest_planned_end_ms": latest_end,
                    "task_count": count,
                },
                "jobs": jobs_map.get(mid, []),
            })

            # overall roll-up
            overall["total_estimated_hours"] += total_est
            overall["task_count"] += count
            if latest_end is not None and (
                overall["latest_planned_end_ms"] is None or latest_end > overall["latest_planned_end_ms"]
            ):
                overall["latest_planned_end_ms"] = latest_end

        return Response({
            "machines": items,
            "overall_totals": overall,
        }, status=status.HTTP_200_OK)
    
class MachineTimelineView(APIView):
    """
    GET /machining/analytics/machine-timeline/
        ?machine_fk=<id|all>   (omit or 'all' => all machines)
        &start_after=<ms|sec>
        &start_before=<ms|sec>

    Enforces a maximum window of 7 full days.
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        machine_param = request.query_params.get('machine_fk')
        start_after = request.query_params.get('start_after')
        start_before = request.query_params.get('start_before')

        # Parse numbers safely
        def _parse_ms(x):
            if x is None or x == "":
                return None
            try:
                v = int(x)
                return v  # normalization to ms happens later
            except ValueError:
                return None

        start_after_ms = _parse_ms(start_after)
        start_before_ms = _parse_ms(start_before)

        # Validate/enforce 7-day window
        try:
            start_after_ms, start_before_ms = _ensure_valid_range(start_after_ms, start_before_ms)
        except ValueError as ve:
            return Response({"error": str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except OverflowError as oe:
            return Response({"error": str(oe)}, status=status.HTTP_400_BAD_REQUEST)

        # Machine selection
        if machine_param and machine_param.lower() != "all":
            try:
                machine_ids = [int(machine_param)]
            except (TypeError, ValueError):
                return Response({"error": "machine_fk must be an integer id or 'all'."}, status=400)
            machines = Machine.objects.filter(id__in=machine_ids)
        else:
            machines = Machine.objects.filter(used_in="machining").only("id", "name")
            machine_ids = list(machines.values_list("id", flat=True))

        # Build timelines in bulk
        timelines = _build_bulk_machine_timelines(machine_ids, start_after_ms, start_before_ms)

        # Stitch response
        machines_by_id = {m.id: m for m in machines}
        items = []
        overall = {"productive_seconds": 0, "hold_seconds": 0, "idle_seconds": 0}

        for mid in machine_ids:
            m = machines_by_id.get(mid)
            name = getattr(m, "name", None)
            data = timelines.get(mid, {"segments": [], "totals": {"productive_seconds": 0, "hold_seconds": 0, "idle_seconds": 0}})
            # (Optional) serialize segments
            # segments = MachineTimelineSegmentSerializer(data["segments"], many=True).data
            segments = data["segments"]
            totals = data["totals"]

            overall["productive_seconds"] += totals["productive_seconds"]
            overall["hold_seconds"] += totals["hold_seconds"]
            overall["idle_seconds"] += totals["idle_seconds"]

            items.append({
                "machine_id": mid,
                "machine_name": name,
                "segments": segments,
                "totals": totals,
            })

        return Response({
            "range": {"start_after_ms": start_after_ms, "start_before_ms": start_before_ms},
            "machines": items,
            "overall_totals": overall,
        }, status=status.HTTP_200_OK)
    

class JobHoursReportView(APIView):
    """
    GET /machining/reports/job-hours/?q=<partial job_no>&start_after=<ms|sec>&start_before=<ms|sec>
    - q: partial job_no (required). Matches Task.job_no via icontains.
    - Optional start_after / start_before to constrain by timer.start_time (epoch ms or seconds).
    Returns:
    {
      "query": "...",
      "job_nos": ["J-1001", "J-1001A", ...],
      "results": [
        {
          "job_no": "J-1001",
          "users": [
            {"user": "alice", "weekday_work": 12.5, "after_hours": 3.0, "sunday": 0.0, "total": 15.5},
            {"user": "bob",   "weekday_work":  8.0, "after_hours": 5.5, "sunday": 2.0, "total": 15.5}
          ],
          "totals": {"weekday_work": 20.5, "after_hours": 8.5, "sunday": 2.0, "total": 31.0}
        },
        ...
      ]
    }
    """
    permission_classes = [IsAdmin]

    def _parse_ms(self, x):
        if x is None or x == "":
            return None
        try:
            v = int(x)
            return v * 1000 if v < 1_000_000_000_000 else v
        except ValueError:
            return None

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response({"error": "q (partial job_no) is required"}, status=400)

        start_after_ms = self._parse_ms(request.query_params.get("start_after"))
        start_before_ms = self._parse_ms(request.query_params.get("start_before"))

        # Find all matching job_nos (non-null, non-empty), keep stable ordering
        matched_job_nos_qs = (
            Task.objects
            .filter(job_no__isnull=False)
            .filter(job_no__icontains=q)
            .order_by("job_no")
            .values_list("job_no", flat=True)
            .distinct()
        )
        job_nos = list(matched_job_nos_qs)

        if not job_nos:
            return Response({"query": q, "job_nos": [], "results": []}, status=200)

        # Fetch relevant timers once; we slice by job_no in Python per bucket calc
        timers = (
            Timer.objects
            .select_related("user").prefetch_related("issue_key")
            .filter(issue_key__job_no__in=job_nos, finish_time__isnull=False)
        )
        if start_after_ms is not None:
            timers = timers.filter(start_time__gte=start_after_ms)
        if start_before_ms is not None:
            timers = timers.filter(start_time__lte=start_before_ms)

        # Aggregate per (job_no -> user -> buckets)
        per_job_user = defaultdict(lambda: defaultdict(lambda: {"weekday_work": 0.0, "after_hours": 0.0, "sunday": 0.0}))

        for t in timers:
            buckets = categorize_timer_segments(t.start_time, t.finish_time)
            j = t.issue_key.job_no or ""
            u = t.user.username
            d = per_job_user[j][u]
            d["weekday_work"] += buckets["weekday_work"] / 3600.0
            d["after_hours"]  += buckets["after_hours"]  / 3600.0
            d["sunday"]       += buckets["sunday"]       / 3600.0

        # Build response
        results = []
        for j in job_nos:
            users_map = per_job_user.get(j, {})
            users_list = []
            totals = {"weekday_work": 0.0, "after_hours": 0.0, "sunday": 0.0, "total": 0.0}

            for user, vals in sorted(users_map.items(), key=lambda kv: kv[0]):  # sort by username
                ww = round(vals["weekday_work"], 2)
                ah = round(vals["after_hours"], 2)
                su = round(vals["sunday"], 2)
                tot = round(ww + ah + su, 2)
                users_list.append({"user": user, "weekday_work": ww, "after_hours": ah, "sunday": su, "total": tot})

                totals["weekday_work"] += ww
                totals["after_hours"]  += ah
                totals["sunday"]       += su
                totals["total"]        += tot

            # Round totals
            for k in totals:
                totals[k] = round(totals[k], 2)

            results.append({
                "job_no": j,
                "users": users_list,
                "totals": totals,
            })

        return Response({"query": q, "job_nos": job_nos, "results": results}, status=200)
    
    
class JobCostListView(APIView):
    """
    GET /costs/jobs/totals/?job_like=283&startswith=true&min_total=0&ordering=-total_cost
    Returns 1 row per job_no with hours + cost breakdown (+ masking by role).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        job_no   = (request.query_params.get("job_no") or "").strip()
        ordering   = (request.query_params.get("ordering") or "-total_cost").strip()

        qs = JobCostAgg.objects.all()
        if job_no:
            field = "job_no_cached__icontains"
            qs = qs.filter(**{field: job_no})

        agg = (
            qs.values("job_no_cached")
              .annotate(
                  hours_ww=Sum("hours_ww"),
                  hours_ah=Sum("hours_ah"),
                  hours_su=Sum("hours_su"),
                  cost_ww=Sum("cost_ww"),
                  cost_ah=Sum("cost_ah"),
                  cost_su=Sum("cost_su"),
                  total_cost=Sum("total_cost"),
                  updated_at=Max("updated_at"),
              )
        )

        allowed = {
            "job_no": "job_no_cached", "-job_no": "-job_no_cached",
            "total_cost": "total_cost", "-total_cost": "-total_cost",
            "updated_at": "updated_at", "-updated_at": "-updated_at",
        }
        agg = agg.order_by(allowed.get(ordering, "-total_cost"))

        results = []
        for row in agg:
            item = {
                "job_no": row["job_no_cached"],
                "hours": {
                    "weekday_work": float(row["hours_ww"] or 0),
                    "after_hours":  float(row["hours_ah"] or 0),
                    "sunday":       float(row["hours_su"] or 0),
                },
                "updated_at": row["updated_at"],
            }

            item["costs"] = {
                "weekday_work": float(row["cost_ww"] or 0),
                "after_hours":  float(row["cost_ah"] or 0),
                "sunday":       float(row["cost_su"] or 0),
            }
            item["total_cost"] = float(row["total_cost"] or 0)
            item["currency"] = "EUR"


            results.append(item)

        return Response({"count": len(results), "results": results}, status=200)
    
class JobCostDetailView(APIView):
    """
    GET /costs/jobs/users/<job_no>/
    GET /costs/jobs/users/?job_like=283

    Returns ONLY per-user rows (aggregated across matched jobs) + per-user issue list with status.
    - management/superusers/staff: hours + full costs per user + issues[{key,status}]
    - manufacturing/planning: hours only + issues[{key,status}] (no money)
    - others: 403
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, job_no: str | None = None):
        # ----- access control -----
        if not can_view_all_users_hours(request.user):
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # ----- query params -----
        job_like = (request.query_params.get("job_like") or "").strip()
        ordering = (request.query_params.get("ordering") or "-total_cost").strip()

        # ----- filters (exact job or partial) -----
        agg_filter = {}
        if job_like:
            agg_filter["job_no_cached__icontains"] = job_like  # switch to __istartswith if preferred
        elif job_no:
            agg_filter["job_no_cached"] = job_no
        else:
            return Response({"detail": "Provide job_no path param or ?job_like=..."}, status=400)

        # ----- base per-user aggregation across matched jobs -----
        users_qs = (
            JobCostAggUser.objects
            .filter(**agg_filter)
            .select_related("user")
            .values("user_id", "user__username", "currency")
            .annotate(
                hours_ww=Sum("hours_ww"),
                hours_ah=Sum("hours_ah"),
                hours_su=Sum("hours_su"),
                cost_ww=Sum("cost_ww"),
                cost_ah=Sum("cost_ah"),
                cost_su=Sum("cost_su"),
                total_cost=Sum("total_cost"),
                updated_at=Max("updated_at"),
            )
        )

        # Safe ordering options
        allowed_ordering = {
            "user": "user__username", "-user": "-user__username",
            "total_cost": "total_cost", "-total_cost": "-total_cost",
            "hours": "hours_ww", "-hours": "-hours_ww",  # proxy by weekday_work hours
            "updated_at": "updated_at", "-updated_at": "-updated_at",
        }
        users_qs = users_qs.order_by(allowed_ordering.get(ordering, "-total_cost"))

        # ----- collect distinct (user_id -> {task_ids}) for issues shown in report -----
        user_task_ids = defaultdict(set)
        for uid, tid in (
            JobCostAggUser.objects
            .filter(**agg_filter)
            .values_list("user_id", "task_id")
            .distinct()
        ):
            if tid:
                user_task_ids[uid].add(tid)

        # Flatten all task ids into one set (single fetch)
        all_task_ids = set()
        for s in user_task_ids.values():
            all_task_ids.update(s)

        # If no tasks, we can short-circuit building issue lists
        tasks_map = {}
        if all_task_ids:
            # ----- annotate tasks with "has_open_timer" and derive status -----
            from django.contrib.contenttypes.models import ContentType
            task_content_type = ContentType.objects.get_for_model(Task)
            open_timer_qs = Timer.objects.filter(content_type=task_content_type, object_id=OuterRef("pk"), finish_time__isnull=True)
            tasks_with_status = (
                Task.objects
                .filter(pk__in=all_task_ids)
                .annotate(
                    has_open_timer=Exists(open_timer_qs),
                    status=Case(
                        When(completion_date__isnull=False, then=Value("completed")),
                        When(has_open_timer=True, then=Value("in_progress")),
                        default=Value("waiting"),
                        output_field=CharField(),
                    ),
                )
                .values("key", "status")
            )
            # Build a quick lookup: task_id -> {key, status}
            tasks_map = {t["key"]: {"key": t["key"], "status": t["status"]} for t in tasks_with_status}

        # ----- mask money by role -----
        show_full = can_view_all_money(request.user)
        show_hours_only = can_view_header_totals_only(request.user)

        # ----- assemble payload -----
        results = []
        for u in users_qs:
            uid = u["user_id"]

            # Build issues list for this user (sorted by key)
            issues_for_user = []
            for tid in sorted(user_task_ids.get(uid, set())):
                meta = tasks_map.get(tid)
                if not meta or not meta["key"]:
                    continue
                issues_for_user.append({"key": meta["key"], "status": meta["status"]})

            item = {
                "user_id": uid,
                "user": u["user__username"],
                "issues": issues_for_user,                 # <-- [{"key": "TI-00123", "status": "in_progress"}, ...]
                "issue_count": len(issues_for_user),
                "hours": {
                    "weekday_work": float(u["hours_ww"] or 0),
                    "after_hours":  float(u["hours_ah"] or 0),
                    "sunday":       float(u["hours_su"] or 0),
                },
                "updated_at": u["updated_at"],
            }

            if show_full:
                item["currency"] = u["currency"]
                item["costs"] = {
                    "weekday_work": float(u["cost_ww"] or 0),
                    "after_hours":  float(u["cost_ah"] or 0),
                    "sunday":       float(u["cost_su"] or 0),
                }
                item["total_cost"] = float(u["total_cost"] or 0)
            elif show_hours_only:
                item["currency"] = None
                item["costs"] = {"weekday_work": None, "after_hours": None, "sunday": None}
                item["total_cost"] = None

            results.append(item)

        return Response({"count": len(results), "results": results}, status=200)