from rest_framework.response import Response

from django.db.models import Sum, Max, F, OuterRef, Exists, Q, Case, When, Value, CharField, ExpressionWrapper, FloatField
from django.db.models import F
from django.db.models.functions import Coalesce
from django.db.models.functions import Coalesce 
from machines.models import Machine
from machining.filters import TaskFilter
from machining.permissions import can_view_all_money, can_view_all_users_hours, can_view_header_totals_only
from .models import Task
from tasks.models import Timer, TaskKeyCounter
from tasks.view_mixins import TaskFileMixin
from machining.services.timers import categorize_timer_segments, _get_business_tz, W_START, W_END 
from users.permissions import IsAdmin, IsMachiningUserOrAdmin 
from .models import JobCostAgg, JobCostAggUser, Task
from tasks.views import GenericMarkTaskCompletedView, GenericTimerDetailView, GenericTimerListView, GenericTimerManualEntryView, GenericTimerReportView, GenericTimerStartView, GenericTimerStopView, GenericUnmarkTaskCompletedView
from .serializers import HoldTaskSerializer, PlanningListItemSerializer, ProductionPlanSerializer, TaskPlanBulkListSerializer, TaskPlanUpdateItemSerializer, TaskSerializer
from django.db.models import Q, Count
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, ModelViewSet
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from config.pagination import CustomPageNumberPagination  # ✅ Use your custom paginator
from rest_framework.filters import OrderingFilter
from django.db import transaction
from rest_framework import permissions, status
from .services.timeline import _build_bulk_machine_timelines, _ensure_valid_range  # _parse_ms is small; OK to re-use
from rest_framework import status
from tasks.views import GenericPlanningBulkSaveView, GenericPlanningListView, GenericProductionPlanView
from collections import defaultdict


class TimerStartView(GenericTimerStartView):
    """
    Starts a timer for a 'machining' task.
    Inherits all logic from the generic view and passes the task_type.
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='machining')

# API View for maintenance to be able to stop maintenance timers.
class TimerStopView(GenericTimerStopView):
    """
    Stops any timer. The logic is already generic.
    """
    permission_classes = [IsAuthenticated] # Or your specific permission

class TimerManualEntryView(GenericTimerManualEntryView):
    """
    Creates a manual timer for a 'machining' task.
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='machining')

class TimerListView(GenericTimerListView):
    """
    Lists timers for 'machining' tasks.
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='machining')

class TimerDetailView(GenericTimerDetailView):
    """
    Retrieve, update, or delete a 'machining' timer instance.
    """
    permission_classes = [IsMachiningUserOrAdmin]

class TimerReportView(GenericTimerReportView):
    """
    Generates aggregate reports for 'machining' timers.
    """
    permission_classes = [IsAdmin]

    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='machining')


class TaskViewSet(TaskFileMixin, ModelViewSet):
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
        return Task.objects.filter(is_hold_task=False).select_related('machine_fk').prefetch_related('issue_key').annotate(
            total_hours_spent=Coalesce(
                ExpressionWrapper(
                    Sum('issue_key__finish_time', filter=Q(issue_key__finish_time__isnull=False)) -
                    Sum('issue_key__start_time', filter=Q(issue_key__finish_time__isnull=False)),
                    output_field=FloatField()
                ) / 3600000.0,
                Value(0.0)
            )
        )
    
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


class MarkTaskCompletedView(GenericMarkTaskCompletedView):
    permission_classes = [IsMachiningUserOrAdmin]

    def post(self, request):
        return super().post(request, task_type='machining')

class UnmarkTaskCompletedView(GenericUnmarkTaskCompletedView):
    permission_classes = [IsAdmin]

    def post(self, request):
        return super().post(request, task_type='machining')
        
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

class PlanningListView(GenericPlanningListView):
    """
    GET /machining/planning/list/?machine_fk=5&only_in_plan=false&start_after=<ms|sec>&start_before=<ms|sec>
    Inherits from the generic planning list view, providing machining-specifics.
    """
    permission_classes = [IsMachiningUserOrAdmin]
    task_model = Task
    serializer_class = PlanningListItemSerializer
    resource_fk_field = 'machine_fk'


class ProductionPlanView(GenericProductionPlanView):
    """
    Inherits from the generic production plan view, providing machining-specifics.
    """
    permission_classes = [IsMachiningUserOrAdmin]
    task_model = Task
    serializer_class = ProductionPlanSerializer
    resource_fk_field = 'machine_fk'

class PlanningBulkSaveView(GenericPlanningBulkSaveView):
    """
    Inherits from the generic bulk save view, providing machining-specifics.
    """
    permission_classes = [IsMachiningUserOrAdmin]
    task_model = Task
    item_serializer_class = TaskPlanUpdateItemSerializer
    bulk_list_serializer_class = TaskPlanBulkListSerializer
    response_serializer_class = PlanningListItemSerializer
    resource_fk_field = 'machine_fk'
    

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


class DailyEfficiencyReportView(APIView):
    """
    GET /machining/reports/daily-efficiency/?date=2024-01-15

    Returns a daily efficiency report showing tasks each user worked on during the selected date.
    For each task, displays:
    - Duration worked on the selected date
    - Total hours spent up to and including the selected date
    - Estimated hours
    - Efficiency (estimated_hours / total_hours_spent)

    Only shows tasks that were worked on during the selected date.
    Total hours spent and efficiency are calculated based on timers up to and including the selected date.
    Only includes users with team='machining'.

    Response shape:
    {
      "date": "2024-01-15",
      "users": [
        {
          "user_id": 1,
          "username": "john",
          "first_name": "John",
          "last_name": "Doe",
          "tasks": [
            {
              "task_key": "TI-001",
              "task_name": "Task 1",
              "job_no": "J-100",
              "machine_name": "Doosan DBC130L II",
              "daily_duration_hours": 2.5,
              "estimated_hours": 5.0,
              "total_hours_spent": 6.0,
              "efficiency": 0.83
            }
          ],
          "total_daily_hours": 8.5
        }
      ]
    }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        from datetime import datetime, date, time
        from django.contrib.auth.models import User
        from django.utils import timezone
        from collections import defaultdict

        # Parse date parameter (default to today)
        date_str = request.query_params.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
        else:
            report_date = timezone.now().date()

        # Get timezone using existing utility
        tz_business = _get_business_tz()

        # Calculate day boundaries in UTC (epoch ms)
        day_start_dt = datetime.combine(report_date, time(0, 0), tz_business)
        day_end_dt = datetime.combine(report_date, time(23, 59, 59), tz_business)
        day_start_ms = int(day_start_dt.timestamp() * 1000)
        day_end_ms = int(day_end_dt.timestamp() * 1000)
        now_ms = int(timezone.now().timestamp() * 1000)

        # Get all timers for this day from users with team='machining'
        timers = (
            Timer.objects
            .select_related('user', 'machine_fk', 'user__profile')
            .prefetch_related('issue_key')
            .filter(
                start_time__gte=day_start_ms,
                start_time__lt=day_end_ms + 86400000,
                user__profile__team='machining'
            )
            .order_by('user_id', 'start_time')
        )

        # Group timers by user and task
        user_task_timers = defaultdict(lambda: defaultdict(list))
        task_keys_set = set()

        for timer in timers:
            # Only include timers that actually overlap with the report date
            timer_end = timer.finish_time or now_ms
            if timer_end < day_start_ms or timer.start_time > day_end_ms:
                continue

            # Only include finished timers for efficiency calculation
            if timer.finish_time is None:
                continue

            # Clip timer to day boundaries
            timer_start = max(timer.start_time, day_start_ms)
            timer_end_clipped = min(timer_end, day_end_ms, now_ms)

            if timer_end_clipped <= timer_start:
                continue

            task = timer.issue_key
            if not task:
                continue

            task_key = getattr(task, 'key', None)
            if not task_key:
                continue

            # Skip hold tasks
            if getattr(task, 'is_hold_task', False):
                continue

            task_keys_set.add(task_key)

            duration_ms = timer_end_clipped - timer_start

            user_task_timers[timer.user_id][task_key].append({
                "duration_ms": duration_ms,
                "task_obj": task,
                "machine_name": timer.machine_fk.name if timer.machine_fk else None,
            })

        # Pre-calculate total_hours_spent for all tasks up to and including the chosen date (bulk query for performance)
        task_totals = {}
        if task_keys_set:
            tasks_with_timers = Task.objects.filter(key__in=task_keys_set).prefetch_related('issue_key')
            for task in tasks_with_timers:
                # Calculate total hours spent across all timers for this task up to and including the chosen date
                # Filter timers that finished on or before the end of the chosen date
                task_timers = task.issue_key.exclude(finish_time__isnull=True).filter(finish_time__lte=day_end_ms)
                total_ms = sum(
                    (t.finish_time - t.start_time)
                    for t in task_timers
                    if t.start_time is not None and t.finish_time is not None and t.finish_time > t.start_time
                )
                total_hours = round(total_ms / 3600000.0, 2) if total_ms > 0 else 0.0
                task_totals[task.key] = {
                    "estimated_hours": float(task.estimated_hours) if task.estimated_hours else None,
                    "total_hours_spent": total_hours,
                    "name": task.name,
                    "job_no": task.job_no,
                }

        # Build response for each user
        users_data = []
        user_ids = list(user_task_timers.keys())
        users = User.objects.filter(
            id__in=user_ids,
            profile__team='machining'
        ).select_related('profile')
        users_by_id = {u.id: u for u in users}

        for user_id, tasks_dict in user_task_timers.items():
            user = users_by_id.get(user_id)
            if not user:
                continue

            tasks_list = []
            total_daily_ms = 0

            for task_key, timer_list in tasks_dict.items():
                task_info = task_totals.get(task_key, {})

                # Sum up duration for this task on the selected date
                daily_duration_ms = sum(t["duration_ms"] for t in timer_list)
                daily_duration_hours = round(daily_duration_ms / 3600000.0, 2)
                total_daily_ms += daily_duration_ms

                # Get machine name (use first timer's machine)
                machine_name = timer_list[0]["machine_name"] if timer_list else None

                # Calculate efficiency
                estimated_hours = task_info.get("estimated_hours")
                total_hours_spent = task_info.get("total_hours_spent", 0.0)

                efficiency = None
                if estimated_hours and total_hours_spent and total_hours_spent > 0:
                    efficiency = round(estimated_hours / total_hours_spent, 2) * 100

                tasks_list.append({
                    "task_key": task_key,
                    "task_name": task_info.get("name"),
                    "job_no": task_info.get("job_no"),
                    "machine_name": machine_name,
                    "daily_duration_hours": daily_duration_hours,
                    "estimated_hours": estimated_hours,
                    "total_hours_spent": total_hours_spent,
                    "efficiency": efficiency,
                })

            # Sort tasks by task_key
            tasks_list.sort(key=lambda x: x["task_key"])

            total_daily_hours = round(total_daily_ms / 3600000.0, 2)

            users_data.append({
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "tasks": tasks_list,
                "total_daily_hours": total_daily_hours,
            })

        # Sort by username
        users_data.sort(key=lambda x: x['username'])

        return Response({
            "date": report_date.isoformat(),
            "users": users_data,
        }, status=200)


class DailyUserReportView(APIView):
    """
    GET /machining/reports/daily-user-report/?date=2024-01-15
    
    Returns a daily report showing what each user did during the day:
    - Tasks they worked on (with duration in minutes, estimated hours, and total hours spent)
    - Idle time (gaps between timers within working hours)
    - Total working time and idle time
    - Total tasks completed by the user
    
    Only includes users with team='machining'.
    
    Response shape:
    {
      "date": "2024-01-15",
      "users": [
        {
          "user_id": 1,
          "username": "john",
          "first_name": "John",
          "last_name": "Doe",
          "tasks": [
            {
              "timer_id": 123,
              "task_key": "TI-001",
              "task_name": "Task 1",
              "job_no": "J-100",
              "start_time": 1705312800000,
              "finish_time": 1705316400000,
              "duration_minutes": 60,
              "estimated_hours": 8.0,
              "total_hours_spent": 3.5,
              "comment": "Worked on task",
              "machine_name": "Doosan DBC130L II",
              "manual_entry": false
            }
          ],
          "idle_periods": [
            {
              "start_time": 1705316400000,
              "finish_time": 1705318200000,
              "duration_minutes": 30
            }
          ],
          "total_work_hours": 8.0,
          "total_idle_hours": 1.5,
          "total_tasks_completed": 15
        }
      ]
    }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def _get_working_hours_for_date(self, date_obj, tz):
        """Get working hours window for a specific date (07:30-17:00 on weekdays)"""
        from datetime import datetime
        weekday = date_obj.weekday()  # 0=Mon, 6=Sun
        
        if weekday >= 5:  # Saturday or Sunday
            return None, None
        
        work_start = datetime.combine(date_obj, W_START, tz)
        work_end = datetime.combine(date_obj, W_END, tz)
        
        return int(work_start.timestamp() * 1000), int(work_end.timestamp() * 1000)

    def _calculate_idle_periods(self, timers, work_start_ms, work_end_ms, now_ms):
        """Calculate idle periods between timers within working hours"""
        idle_periods = []
        
        # If no working hours defined (e.g., weekend), return empty
        if not work_start_ms or not work_end_ms:
            return idle_periods
        
        if not timers:
            # If no timers, the entire working day is idle
            idle_periods.append({
                "start_time": work_start_ms,
                "finish_time": min(work_end_ms, now_ms),
                "duration_minutes": round((min(work_end_ms, now_ms) - work_start_ms) / 60000.0, 0)
            })
            return idle_periods
        
        # Sort timers by start_time
        sorted_timers = sorted(timers, key=lambda t: t['start_time'])
        
        # Check for idle time before first timer (within working hours)
        first_timer_start = sorted_timers[0]['start_time']
        if first_timer_start > work_start_ms:
            idle_start = work_start_ms
            idle_end = min(first_timer_start, work_end_ms, now_ms)
            if idle_end > idle_start:
                idle_periods.append({
                    "start_time": idle_start,
                    "finish_time": idle_end,
                    "duration_minutes": round((idle_end - idle_start) / 60000.0, 0)
                })
        
        # Check for idle time between timers (within working hours)
        for i in range(len(sorted_timers) - 1):
            # Use actual finish time if timer finished, otherwise use clipped finish_time
            if sorted_timers[i].get('timer_finished') and sorted_timers[i].get('actual_finish_time'):
                current_end = sorted_timers[i]['actual_finish_time']
            else:
                # Timer still running, use clipped time
                current_end = sorted_timers[i]['finish_time']
            
            next_start = sorted_timers[i + 1]['start_time']
            
            if next_start > current_end:
                # Only count idle time if it's within working hours
                idle_start = max(current_end, work_start_ms)
                idle_end = min(next_start, work_end_ms, now_ms)
                if idle_end > idle_start:
                    idle_periods.append({
                        "start_time": idle_start,
                        "finish_time": idle_end,
                        "duration_minutes": round((idle_end - idle_start) / 60000.0, 0)
                    })
        
        # Check for idle time after last timer (within working hours)
        if sorted_timers:
            last_timer = sorted_timers[-1]
            # Only count idle time if the timer actually finished (not still running)
            if last_timer.get('timer_finished') and last_timer.get('actual_finish_time'):
                last_timer_end = last_timer['actual_finish_time']
                # Check if timer ended before work end time
                if last_timer_end < work_end_ms:
                    idle_start = max(last_timer_end, work_start_ms)
                    idle_end = min(work_end_ms, now_ms)
                    if idle_end > idle_start:
                        idle_periods.append({
                            "start_time": idle_start,
                            "finish_time": idle_end,
                            "duration_minutes": round((idle_end - idle_start) / 60000.0, 0)
                        })
        
        return idle_periods

    def get(self, request):
        from datetime import datetime, date, time
        from django.contrib.auth.models import User
        from django.utils import timezone
        from collections import defaultdict
        
        # Parse date parameter (default to today)
        date_str = request.query_params.get('date')
        if date_str:
            try:
                report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
        else:
            report_date = timezone.now().date()
        
        # Get timezone using existing utility
        tz_business = _get_business_tz()
        
        # Calculate day boundaries in UTC (epoch ms)
        day_start_dt = datetime.combine(report_date, time(0, 0), tz_business)
        day_end_dt = datetime.combine(report_date, time(23, 59, 59), tz_business)
        day_start_ms = int(day_start_dt.timestamp() * 1000)
        day_end_ms = int(day_end_dt.timestamp() * 1000)
        now_ms = int(timezone.now().timestamp() * 1000)
        
        # Get working hours for this date
        work_start_ms, work_end_ms = self._get_working_hours_for_date(report_date, tz_business)
        
        # Get all timers for this day from users with team='machining'
        # Note: issue_key is a GenericForeignKey, so it can't be used with select_related
        timers = (
            Timer.objects
            .select_related('user', 'machine_fk', 'user__profile')
            .prefetch_related('issue_key')
            .filter(
                start_time__gte=day_start_ms,
                start_time__lt=day_end_ms + 86400000,  # Include next day start for finish_time
                user__profile__team='machining'  # Only machining team users
            )
            .order_by('user_id', 'start_time')
        )
        
        # Group timers by user and collect task keys for bulk query
        user_timers = defaultdict(list)
        task_keys_set = set()
        
        for timer in timers:
            # Only include timers that actually overlap with the report date
            timer_end = timer.finish_time or now_ms
            if timer_end < day_start_ms or timer.start_time > day_end_ms:
                continue
            
            # Clip timer to day boundaries
            timer_start = max(timer.start_time, day_start_ms)
            timer_end_clipped = min(timer_end, day_end_ms, now_ms)
            
            if timer_end_clipped <= timer_start:
                continue
            
            task = timer.issue_key
            task_key = getattr(task, 'key', None) if task else None
            if task_key:
                task_keys_set.add(task_key)
            
            task_name = getattr(task, 'name', None) if task else None
            job_no = getattr(task, 'job_no', None) if task else None
            
            duration_ms = timer_end_clipped - timer_start
            duration_minutes = round(duration_ms / 60000.0, 0)
            
            # Store whether timer actually finished and its actual end time for idle calculation
            timer_finished = timer.finish_time is not None
            actual_timer_end = timer.finish_time if timer_finished else None
            
            user_timers[timer.user_id].append({
                "timer_id": timer.id,  # Store timer ID
                "start_time": timer_start,
                "finish_time": timer_end_clipped,
                "timer_finished": timer_finished,  # Track if timer actually finished
                "actual_finish_time": actual_timer_end,  # Store actual end time (None if still running)
                "task_key": task_key,
                "task_name": task_name,
                "job_no": job_no,
                "duration_minutes": duration_minutes,
                "comment": timer.comment,
                "machine_name": timer.machine_fk.name if timer.machine_fk else None,
                "manual_entry": timer.manual_entry,
                "_task_obj": task,  # Store task object for later use
            })
        
        # Pre-calculate total_hours_spent for all tasks (bulk query for performance)
        task_totals = {}
        if task_keys_set:
            tasks_with_timers = Task.objects.filter(key__in=task_keys_set).prefetch_related('issue_key')
            for task in tasks_with_timers:
                # Calculate total hours spent across all timers for this task
                task_timers = task.issue_key.exclude(finish_time__isnull=True)
                total_ms = sum(
                    (t.finish_time - t.start_time) 
                    for t in task_timers 
                    if t.start_time is not None and t.finish_time is not None and t.finish_time > t.start_time
                )
                total_hours = round(total_ms / 3600000.0, 2) if total_ms > 0 else 0.0
                task_totals[task.key] = {
                    "estimated_hours": float(task.estimated_hours) if task.estimated_hours else None,
                    "total_hours_spent": total_hours,
                }
        
        # Build response for each user
        # Filter to only include users with team=machining
        users_data = []
        user_ids = list(user_timers.keys())
        users = User.objects.filter(
            id__in=user_ids,
            profile__team='machining'
        ).select_related('profile')
        users_by_id = {u.id: u for u in users}
        
        # Pre-calculate total tasks completed on this day for all machining users
        completed_task_counts = {}
        if users_by_id:
            from django.db.models import Count
            completed_counts = (
                Task.objects
                .filter(
                    completed_by_id__in=users_by_id.keys(),
                    completion_date__gte=day_start_ms,
                    completion_date__lt=day_end_ms + 86400000  # Include up to end of day
                )
                .values('completed_by_id')
                .annotate(count=Count('key'))
            )
            completed_task_counts = {item['completed_by_id']: item['count'] for item in completed_counts}
        
        for user_id, timer_list in user_timers.items():
            user = users_by_id.get(user_id)
            if not user:
                continue
            
            # Enrich timer list with task totals and remove internal _task_obj
            enriched_tasks = []
            enriched_hold_tasks = []
            for timer_data in timer_list:
                task_key = timer_data.get("task_key")
                task_info = task_totals.get(task_key, {}) if task_key else {}
                
                enriched_task = {
                    "timer_id": timer_data.get("timer_id"),
                    "start_time": timer_data["start_time"],
                    "finish_time": timer_data["finish_time"],
                    "task_key": timer_data["task_key"],
                    "task_name": timer_data["task_name"],
                    "job_no": timer_data["job_no"],
                    "duration_minutes": timer_data["duration_minutes"],
                    "estimated_hours": task_info.get("estimated_hours"),
                    "total_hours_spent": task_info.get("total_hours_spent", 0.0),
                    "comment": timer_data["comment"],
                    "machine_name": timer_data["machine_name"],
                    "manual_entry": timer_data["manual_entry"],
                }

                task_obj = timer_data.get("_task_obj")
                if task_obj and getattr(task_obj, 'is_hold_task', False):
                    enriched_hold_tasks.append(enriched_task)
                else:
                    enriched_tasks.append(enriched_task)
            
            # Calculate idle periods
            idle_periods = self._calculate_idle_periods(
                timer_list, 
                work_start_ms, 
                work_end_ms, 
                now_ms
            )
            
            # Calculate totals
            regular_task_timers = [t for t in timer_list if not (t.get("_task_obj") and getattr(t.get("_task_obj"), 'is_hold_task', False))]
            hold_task_timers = [t for t in timer_list if t.get("_task_obj") and getattr(t.get("_task_obj"), 'is_hold_task', False)]
            
            total_work_ms = 0
            if work_start_ms and work_end_ms:
                for t in regular_task_timers:
                    overlap_start = max(t['start_time'], work_start_ms)
                    overlap_end = min(t['finish_time'], work_end_ms)
                    if overlap_end > overlap_start:
                        total_work_ms += (overlap_end - overlap_start)

            total_work_hours = round(total_work_ms / 3600000.0, 2)

            total_hold_ms = 0
            if work_start_ms and work_end_ms:
                for t in hold_task_timers:
                    overlap_start = max(t['start_time'], work_start_ms)
                    overlap_end = min(t['finish_time'], work_end_ms)
                    if overlap_end > overlap_start:
                        total_hold_ms += (overlap_end - overlap_start)

            total_hold_hours = round(total_hold_ms / 3600000.0, 2)
            
            total_idle_ms = sum(
                (p['finish_time'] - p['start_time']) 
                for p in idle_periods
            )
            # Subtract 60 minutes (lunch time) from total idle time
            # Negative values indicate they kept the timer open during lunch
            LUNCH_TIME_MS = 60 * 60 * 1000  # 60 minutes in milliseconds
            total_idle_ms_adjusted = total_idle_ms - LUNCH_TIME_MS
            total_idle_hours = round(total_idle_ms_adjusted / 3600000.0, 2)
            
            # Get total tasks completed by this user
            total_tasks_completed = completed_task_counts.get(user.id, 0)
            
            users_data.append({
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "tasks": enriched_tasks,
                "hold_tasks": enriched_hold_tasks,
                "idle_periods": idle_periods,
                "total_work_hours": total_work_hours,
                "total_hold_hours": total_hold_hours,
                "total_idle_hours": total_idle_hours,
                "total_tasks_completed": total_tasks_completed,
            })
        
        # Sort by username
        users_data.sort(key=lambda x: x['username'])
        
        return Response({
            "date": report_date.isoformat(),
            "users": users_data,
        }, status=200)