import time
import logging
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework import viewsets, mixins
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action

logger = logging.getLogger(__name__)

from .models import CncTask, CncPart, RemnantPlate
from tasks.models import TaskFile
from tasks.views import (
    GenericTimerDetailView,
    GenericTimerListView,
    GenericTimerManualEntryView,
    GenericTimerReportView,
    GenericTimerStartView,
    GenericTimerStopView,
    GenericMarkTaskCompletedView,
    GenericUnmarkTaskCompletedView,
    GenericPlanningListView,
    GenericProductionPlanView,
    GenericPlanningBulkSaveView,
)
from .serializers import (
    CncTaskListSerializer,
    CncTaskDetailSerializer,
    CncPartSerializer,
    CncPartSearchResultSerializer,
    CncTimerSerializer,
    RemnantPlateSerializer,
    CncPlanningListItemSerializer,
    CncProductionPlanSerializer,
    CncTaskPlanUpdateItemSerializer,
    CncTaskPlanBulkListSerializer,
)
from .serializers import CncHoldTaskSerializer
from .filters import CncTaskFilter, RemnantPlateFilter
from tasks.serializers import TaskFileSerializer
from tasks.view_mixins import TaskFileMixin

class TimerStartView(GenericTimerStartView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='cnc_cutting')

class TimerStopView(GenericTimerStopView):
    permission_classes = [IsAuthenticated]

class TimerManualEntryView(GenericTimerManualEntryView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='cnc_cutting')

class TimerListView(GenericTimerListView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='cnc_cutting')

class TimerDetailView(GenericTimerDetailView):
    permission_classes = [IsAuthenticated]

class TimerReportView(GenericTimerReportView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='cnc_cutting')

class MarkTaskCompletedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')


class UnmarkTaskCompletedView(GenericUnmarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')

class MarkTaskWareHouseProcessedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            task = CncTask.objects.get(key=task_key)
            task.processed_by_warehouse = True
            task.processed_warehouse_date = timezone.now().date()
            task.save()
            return Response({'status': 'Task marked as processed by warehouse.'}, status=status.HTTP_200_OK)
        except CncTask.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
# --- Planning Views ---

class PlanningListView(GenericPlanningListView):
    """
    GET /cnc_cutting/planning/list/?machine_fk=...
    """
    permission_classes = [IsAuthenticated]
    task_model = CncTask
    serializer_class = CncPlanningListItemSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CncTaskFilter
    ordering_fields = ['key', 'name', 'nesting_id', 'material', 'thickness_mm', 'completion_date', 'estimated_hours', 'plan_order']
    ordering = ['-key']
    resource_fk_field = 'machine_fk'

class ProductionPlanView(GenericProductionPlanView):
    """
    GET /cnc_cutting/planning/production-plan/?machine_fk=...
    """
    permission_classes = [IsAuthenticated]
    task_model = CncTask
    serializer_class = CncProductionPlanSerializer
    resource_fk_field = 'machine_fk'

class PlanningBulkSaveView(GenericPlanningBulkSaveView):
    """
    POST /cnc_cutting/planning/bulk-save/
    """
    permission_classes = [IsAuthenticated]
    task_model = CncTask
    item_serializer_class = CncTaskPlanUpdateItemSerializer
    bulk_list_serializer_class = CncTaskPlanBulkListSerializer
    response_serializer_class = CncPlanningListItemSerializer
    resource_fk_field = 'machine_fk'


class CncTaskViewSet(TaskFileMixin, ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting CNC tasks.
    Handles multipart/form-data for file uploads.
    """
    # Combine querysets for both list and detail views for efficiency
    queryset = CncTask.objects.select_related('machine_fk').prefetch_related('issue_key', 'parts', 'files', 'plate_usage_records__remnant_plate').annotate(parts_count=Count('parts')).order_by('-key')
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # Important for file uploads
    filterset_class = CncTaskFilter
    ordering_fields = ['key', 'name', 'nesting_id', 'material', 'thickness_mm', 'completion_date', 'estimated_hours', 'plan_order']
    ordering = ['-key']
    
    def get_serializer_class(self):
        """
        Return the appropriate serializer class based on the action.
        - CncTaskListSerializer for the 'list' action.
        - CncTaskDetailSerializer for all other actions (create, retrieve, update).
        """
        if self.action == 'list':
            return CncTaskListSerializer
        return CncTaskDetailSerializer
    
    def get_queryset(self):
        # 'issue_key' is the GenericRelation from tasks.Timer back to this Task
        # prefetch_related works seamlessly with it for great performance.
        return CncTask.objects.select_related('machine_fk').prefetch_related('issue_key', 'parts', 'files', 'plate_usage_records__remnant_plate').annotate(parts_count=Count('parts')).filter(is_hold_task=False).order_by('-key')


class CncHoldTaskViewSet(ModelViewSet):
    """
    ViewSet for listing CNC hold tasks.
    """
    queryset = CncTask.objects.all()
    serializer_class = CncHoldTaskSerializer
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_class = CncTaskFilter

    def get_queryset(self):
        return CncTask.objects.filter(is_hold_task=True)

class CncPartViewSet(ModelViewSet):
    """
    ViewSet for creating, retrieving, updating, and deleting CncPart instances.
    """
    queryset = CncPart.objects.all()
    serializer_class = CncPartSerializer
    permission_classes = [IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        """
        Delete a single CncPart instance.
        Only office users can delete parts.
        """
        # Authorization: Only office users can delete parts
        user = request.user
        if not (user and (user.is_staff or user.is_superuser)):
            return Response(
                {"error": "Only staff users can delete parts."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get the part to delete
        part = self.get_object()

        # Log the deletion
        logger.info(
            f"Deleting part: User={user.username}, PartID={part.id}, "
            f"Task={part.cnc_task.key}, JobNo={part.job_no}, "
            f"ImageNo={part.image_no}, PositionNo={part.position_no}"
        )

        # Perform deletion
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request, *args, **kwargs):
        """
        Handles bulk creation of CncPart instances.
        Expects a POST request to `/api/cnc_cutting/parts/bulk-create/`
        with a list of CncPart objects in the request body.
        """
        # Ensure the serializer handles multiple objects
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)

        # Save all valid instances
        instances = serializer.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

class CncTaskFileViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    ViewSet for deleting a TaskFile.
    """
    queryset = TaskFile.objects.all()
    serializer_class = TaskFileSerializer
    permission_classes = [IsAuthenticated]

class RemnantPlateViewSet(ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting RemnantPlate instances.
    """
    queryset = RemnantPlate.objects.all()
    serializer_class = RemnantPlateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = RemnantPlateFilter
    ordering_fields = ['thickness_mm', 'dimensions', 'quantity', 'material', 'heat_number']
    ordering = ['-id']

    def get_queryset(self):
        """
        By default, for 'list' actions, only show remnant plates that have available quantity
        (i.e., not fully consumed by tasks). This can be changed by using the `unassigned` filter.
        For other actions (retrieve, update, delete), allow access to any remnant plate.
        """
        qs = super().get_queryset()
        if self.action == 'list':
            # Default to showing only plates with available quantity if no specific filter is given.
            if 'unassigned' not in self.request.query_params:
                # Only show plates where the available quantity is greater than 0
                # This requires annotating with usage count and comparing to total quantity
                from django.db.models import Sum, F, Q
                qs = qs.annotate(
                    total_used=Sum('usage_records__quantity_used')
                ).filter(
                    Q(total_used__isnull=True) | Q(total_used__lt=F('quantity'))
                )
        return qs

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request, *args, **kwargs):
        """
        Handles bulk creation of RemnantPlate instances.
        Expects a POST request to `/api/cnc_cutting/remnants/bulk-create/`
        with a list of remnant plate objects in the request body.
        """
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        response_serializer = self.get_serializer(instances, many=True)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CncPartSearchPagination(PageNumberPagination):
    """Custom pagination for CNC part search results."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CncPartSearchView(ListAPIView):
    """
    API view for searching CNC parts by job_no, image_no, and position_no.
    Supports partial matching on all fields and returns the associated CNC task details.
    Returns all parts if no filters are provided (paginated).

    GET /api/cnc_cutting/parts/search/?job_no=...&image_no=...&position_no=...
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CncPartSearchResultSerializer
    pagination_class = CncPartSearchPagination

    def get_queryset(self):
        """
        Search for CNC parts with optional partial filters.
        Query parameters:
        - job_no: Partial match on job number
        - image_no: Partial match on image number
        - position_no: Partial match on position number

        If no filters are provided, returns all parts (paginated).
        """
        queryset = CncPart.objects.select_related('cnc_task').all().order_by('-id')

        # Apply filters if provided
        job_no = self.request.query_params.get('job_no', None)
        image_no = self.request.query_params.get('image_no', None)
        position_no = self.request.query_params.get('position_no', None)

        if job_no:
            queryset = queryset.filter(job_no__icontains=job_no)

        if image_no:
            queryset = queryset.filter(image_no__icontains=image_no)

        if position_no:
            queryset = queryset.filter(position_no__icontains=position_no)

        return queryset


# ---------------------------------------------------------------------------
# CNC Cutting user reports (mirrors machining UserReportView / UserTaskDetailView)
# ---------------------------------------------------------------------------

from collections import defaultdict
from rest_framework.views import APIView
from machining.services.timers import _get_business_tz, W_START, W_END
from tasks.models import Timer


def _cnc_get_working_hours_for_date(date_obj, tz):
    """07:30-17:00 on weekdays, None on weekends."""
    from datetime import datetime
    if date_obj.weekday() >= 5:
        return None, None
    work_start = datetime.combine(date_obj, W_START, tz)
    work_end = datetime.combine(date_obj, W_END, tz)
    return int(work_start.timestamp() * 1000), int(work_end.timestamp() * 1000)


def _cnc_calculate_idle_periods(timers, work_start_ms, work_end_ms, now_ms):
    """Calculate idle gaps between timers within working hours."""
    idle_periods = []
    if not work_start_ms or not work_end_ms:
        return idle_periods

    if not timers:
        idle_periods.append({
            "start_time": work_start_ms,
            "finish_time": min(work_end_ms, now_ms),
            "duration_minutes": round((min(work_end_ms, now_ms) - work_start_ms) / 60000.0, 0),
        })
        return idle_periods

    sorted_timers = sorted(timers, key=lambda t: t['start_time'])

    first_start = sorted_timers[0]['start_time']
    if first_start > work_start_ms:
        idle_end = min(first_start, work_end_ms, now_ms)
        if idle_end > work_start_ms:
            idle_periods.append({
                "start_time": work_start_ms,
                "finish_time": idle_end,
                "duration_minutes": round((idle_end - work_start_ms) / 60000.0, 0),
            })

    for i in range(len(sorted_timers) - 1):
        cur = sorted_timers[i]
        if cur.get('timer_finished') and cur.get('actual_finish_time'):
            current_end = cur['actual_finish_time']
        else:
            current_end = cur['finish_time']
        next_start = sorted_timers[i + 1]['start_time']
        if next_start > current_end:
            idle_start = max(current_end, work_start_ms)
            idle_end = min(next_start, work_end_ms, now_ms)
            if idle_end > idle_start:
                idle_periods.append({
                    "start_time": idle_start,
                    "finish_time": idle_end,
                    "duration_minutes": round((idle_end - idle_start) / 60000.0, 0),
                })

    last = sorted_timers[-1]
    if last.get('timer_finished') and last.get('actual_finish_time'):
        last_end = last['actual_finish_time']
        if last_end < work_end_ms:
            idle_start = max(last_end, work_start_ms)
            idle_end = min(work_end_ms, now_ms)
            if idle_end > idle_start:
                idle_periods.append({
                    "start_time": idle_start,
                    "finish_time": idle_end,
                    "duration_minutes": round((idle_end - idle_start) / 60000.0, 0),
                })

    return idle_periods


def _cnc_get_day_timers(report_date, tz_business, now_ms, user_filter=None):
    """
    Fetch timers for one day, grouped by user_id.
    Returns (user_timers dict, day_start_ms, day_end_ms).
    """
    from datetime import datetime, time as dt_time

    day_start_dt = datetime.combine(report_date, dt_time(0, 0), tz_business)
    day_end_dt = datetime.combine(report_date, dt_time(23, 59, 59), tz_business)
    day_start_ms = int(day_start_dt.timestamp() * 1000)
    day_end_ms = int(day_end_dt.timestamp() * 1000)

    qs = (
        Timer.objects
        .select_related('user', 'machine_fk', 'user__profile')
        .prefetch_related('issue_key')
        .filter(
            start_time__gte=day_start_ms,
            start_time__lt=day_end_ms + 86400000,
            user__groups__name='cutting_team',
        )
        .order_by('user_id', 'start_time')
    )
    if user_filter is not None:
        qs = qs.filter(user_id=user_filter)

    user_timers = defaultdict(list)
    for timer in qs:
        timer_end = timer.finish_time or now_ms
        if timer_end < day_start_ms or timer.start_time > day_end_ms:
            continue
        timer_start = max(timer.start_time, day_start_ms)
        timer_end_clipped = min(timer_end, day_end_ms, now_ms)
        if timer_end_clipped <= timer_start:
            continue

        task = timer.issue_key
        task_key = getattr(task, 'key', None) if task else None
        timer_finished = timer.finish_time is not None

        user_timers[timer.user_id].append({
            "timer_id": timer.id,
            "start_time": timer_start,
            "finish_time": timer_end_clipped,
            "timer_finished": timer_finished,
            "actual_finish_time": timer.finish_time if timer_finished else None,
            "task_key": task_key,
            "task_name": getattr(task, 'name', None) if task else None,
            "nesting_id": getattr(task, 'nesting_id', None) if task else None,
            "material": getattr(task, 'material', None) if task else None,
            "thickness_mm": float(task.thickness_mm) if task and getattr(task, 'thickness_mm', None) else None,
            "duration_minutes": round((timer_end_clipped - timer_start) / 60000.0, 0),
            "comment": timer.comment,
            "machine_name": timer.machine_fk.name if timer.machine_fk else None,
            "manual_entry": timer.manual_entry,
            "_task_obj": task,
        })
    return user_timers, day_start_ms, day_end_ms


def _cnc_compute_day_totals(timer_list, work_start_ms, work_end_ms, now_ms):
    """Return (work_ms, hold_ms, idle_ms_adjusted, task_keys_set) for one user/day."""
    regular = [t for t in timer_list if not (t.get("_task_obj") and getattr(t["_task_obj"], 'is_hold_task', False))]
    hold = [t for t in timer_list if t.get("_task_obj") and getattr(t["_task_obj"], 'is_hold_task', False)]

    work_ms = 0
    if work_start_ms and work_end_ms:
        for t in regular:
            s = max(t['start_time'], work_start_ms)
            e = min(t['finish_time'], work_end_ms)
            if e > s:
                work_ms += (e - s)

    hold_ms = 0
    if work_start_ms and work_end_ms:
        for t in hold:
            s = max(t['start_time'], work_start_ms)
            e = min(t['finish_time'], work_end_ms)
            if e > s:
                hold_ms += (e - s)

    idle_periods = _cnc_calculate_idle_periods(timer_list, work_start_ms, work_end_ms, now_ms)
    total_idle_ms = sum((p['finish_time'] - p['start_time']) for p in idle_periods)
    LUNCH_MS = 60 * 60 * 1000
    idle_ms_adjusted = total_idle_ms - LUNCH_MS

    task_keys = {t['task_key'] for t in timer_list if t.get('task_key')}
    return work_ms, hold_ms, idle_ms_adjusted, task_keys


def _cnc_parts_totals(task_keys):
    """
    Return a dict mapping task_key -> total parts quantity for the given CncTask keys.
    Uses CncPart.quantity (sum per task).
    """
    from django.db.models import Sum
    if not task_keys:
        return {}
    from cnc_cutting.models import CncPart
    rows = (
        CncPart.objects
        .filter(cnc_task_id__in=task_keys)
        .values('cnc_task_id')
        .annotate(total_parts=Sum('quantity'))
    )
    return {row['cnc_task_id']: row['total_parts'] or 0 for row in rows}


class CncUserReportView(APIView):
    """
    GET /cnc-cutting/reports/user-report/?start_date=2024-01-15&end_date=2024-01-19

    Summary report per cutting team user over a date range.

    Response shape:
    {
      "start_date": "2024-01-15",
      "end_date": "2024-01-19",
      "users": [
        {
          "user_id": 1,
          "username": "john",
          "first_name": "John",
          "last_name": "Doe",
          "total_work_hours": 32.5,
          "total_hold_hours": 2.0,
          "total_idle_hours": 4.5,
          "total_tasks_completed": 8,
          "total_tasks_worked_on": 10,
          "total_parts_completed": 320,
          "total_parts_worked_on": 415
        }
      ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import datetime, timedelta, time as dt_time
        from django.contrib.auth.models import User
        from django.utils import timezone
        from django.db.models import Count, Sum
        from cnc_cutting.models import CncTask, CncPart

        start_str = request.query_params.get('start_date')
        end_str = request.query_params.get('end_date')
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else timezone.now().date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else start_date
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        if end_date < start_date:
            return Response({"error": "end_date must be >= start_date"}, status=400)

        tz_business = _get_business_tz()
        now_ms = int(timezone.now().timestamp() * 1000)

        # Fetch all cutting team users upfront so those with no timers still appear
        users = User.objects.filter(groups__name='cutting_team', is_active=True).select_related('profile')
        users_by_id = {u.id: u for u in users}
        if not users_by_id:
            return Response({"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "users": []})

        all_user_ids = set(users_by_id.keys())

        user_work_ms = defaultdict(int)
        user_hold_ms = defaultdict(int)
        user_idle_ms = defaultdict(int)
        user_task_keys = defaultdict(set)

        current_date = start_date
        while current_date <= end_date:
            work_start_ms, work_end_ms = _cnc_get_working_hours_for_date(current_date, tz_business)
            day_user_timers, _, _ = _cnc_get_day_timers(current_date, tz_business, now_ms)

            # Full working day idle for users with no timers on this weekday
            if work_start_ms and work_end_ms:
                window_ms = min(work_end_ms, now_ms) - work_start_ms
                LUNCH_MS = 60 * 60 * 1000
                for uid in all_user_ids:
                    if uid not in day_user_timers:
                        user_idle_ms[uid] += max(window_ms - LUNCH_MS, 0)

            for uid, timer_list in day_user_timers.items():
                work_ms, hold_ms, idle_ms, task_keys = _cnc_compute_day_totals(
                    timer_list, work_start_ms, work_end_ms, now_ms
                )
                user_work_ms[uid] += work_ms
                user_hold_ms[uid] += hold_ms
                user_idle_ms[uid] += idle_ms
                user_task_keys[uid].update(task_keys)

            current_date += timedelta(days=1)

        range_start_ms = int(datetime.combine(start_date, dt_time(0, 0), tz_business).timestamp() * 1000)
        range_end_ms = int(datetime.combine(end_date, dt_time(23, 59, 59), tz_business).timestamp() * 1000)

        # Tasks completed in range with their part counts
        completed_tasks = (
            CncTask.objects
            .filter(
                completed_by_id__in=all_user_ids,
                completion_date__gte=range_start_ms,
                completion_date__lte=range_end_ms,
            )
            .values('completed_by_id', 'key')
        )
        completed_keys_by_user = defaultdict(set)
        for row in completed_tasks:
            completed_keys_by_user[row['completed_by_id']].add(row['key'])

        all_completed_keys = {k for keys in completed_keys_by_user.values() for k in keys}
        all_worked_keys = {k for keys in user_task_keys.values() for k in keys}

        completed_parts_map = _cnc_parts_totals(all_completed_keys)
        worked_parts_map = _cnc_parts_totals(all_worked_keys)

        users_data = []
        for uid, user in users_by_id.items():
            completed_keys = completed_keys_by_user.get(uid, set())
            worked_keys = user_task_keys.get(uid, set())

            total_parts_completed = sum(completed_parts_map.get(k, 0) for k in completed_keys)
            total_parts_worked_on = sum(worked_parts_map.get(k, 0) for k in worked_keys)

            users_data.append({
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "total_work_hours": round(user_work_ms[uid] / 3600000.0, 2),
                "total_hold_hours": round(user_hold_ms[uid] / 3600000.0, 2),
                "total_idle_hours": round(user_idle_ms[uid] / 3600000.0, 2),
                "total_tasks_completed": len(completed_keys),
                "total_tasks_worked_on": len(worked_keys),
                "total_parts_completed": total_parts_completed,
                "total_parts_worked_on": total_parts_worked_on,
            })

        users_data.sort(key=lambda x: x['username'])

        return Response({
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "users": users_data,
        }, status=200)


class CncUserTaskDetailView(APIView):
    """
    GET /cnc-cutting/reports/user-task-detail/?user_id=1&start_date=2024-01-15&end_date=2024-01-19

    Full timer/task detail for a specific cutting team user, grouped by day.
    Includes CNC-specific fields: nesting_id, material, thickness_mm, parts_count.

    Response shape:
    {
      "user_id": 1,
      "username": "john",
      "first_name": "John",
      "last_name": "Doe",
      "start_date": "2024-01-15",
      "end_date": "2024-01-19",
      "days": [
        {
          "date": "2024-01-15",
          "tasks": [
            {
              "timer_id": 123,
              "task_key": "CNC-001",
              "task_name": "Nest 42",
              "nesting_id": "NEST-42",
              "material": "S355",
              "thickness_mm": 20.0,
              "parts_count": 48,
              "status": "completed",
              "completed_by": {"id": 3, "username": "jane", "first_name": "Jane", "last_name": "Doe"},
              "completion_date": 1705316400000,
              "start_time": 1705312800000,
              "finish_time": 1705316400000,
              "duration_minutes": 60,
              "comment": "...",
              "machine_name": "Finn-Power E5",
              "manual_entry": false
            }
          ],
          "hold_tasks": [...],
          "idle_periods": [...]
        }
      ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import datetime, timedelta
        from django.contrib.auth.models import User
        from django.utils import timezone

        user_id_str = request.query_params.get('user_id')
        start_str = request.query_params.get('start_date')
        end_str = request.query_params.get('end_date')

        if not user_id_str:
            return Response({"error": "user_id is required"}, status=400)
        try:
            user_id = int(user_id_str)
        except ValueError:
            return Response({"error": "user_id must be an integer"}, status=400)

        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date() if start_str else timezone.now().date()
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else start_date
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)

        if end_date < start_date:
            return Response({"error": "end_date must be >= start_date"}, status=400)

        try:
            user = User.objects.select_related('profile').get(
                id=user_id, groups__name='cutting_team'
            )
        except User.DoesNotExist:
            return Response({"error": "User not found or not in cutting team"}, status=404)

        tz_business = _get_business_tz()
        now_ms = int(timezone.now().timestamp() * 1000)

        all_timer_lists_by_date = {}
        all_task_keys = set()

        current_date = start_date
        while current_date <= end_date:
            day_user_timers, _, _ = _cnc_get_day_timers(current_date, tz_business, now_ms, user_filter=user_id)
            timer_list = day_user_timers.get(user_id, [])
            all_timer_lists_by_date[current_date] = timer_list
            for t in timer_list:
                if t.get('task_key'):
                    all_task_keys.add(t['task_key'])
            current_date += timedelta(days=1)

        # Bulk-fetch part counts and task completion/estimate info
        parts_map = _cnc_parts_totals(all_task_keys)
        task_info_map = {}
        if all_task_keys:
            tasks_qs = CncTask.objects.filter(key__in=all_task_keys).select_related('completed_by').prefetch_related('timers')
            for t in tasks_qs:
                finished_timers = [
                    tmr for tmr in t.timers.all()
                    if tmr.start_time and tmr.finish_time and tmr.finish_time > tmr.start_time
                ]
                total_ms = sum(tmr.finish_time - tmr.start_time for tmr in finished_timers)
                task_info_map[t.key] = {
                    "status": "completed" if t.completion_date else "in_progress",
                    "completed_by_id": t.completed_by_id,
                    "completed_by_username": t.completed_by.username if t.completed_by else None,
                    "completed_by_first_name": t.completed_by.first_name if t.completed_by else None,
                    "completed_by_last_name": t.completed_by.last_name if t.completed_by else None,
                    "completion_date": t.completion_date,
                    "estimated_hours": float(t.estimated_hours) if t.estimated_hours else None,
                    "total_hours_spent": round(total_ms / 3600000.0, 2) if total_ms > 0 else 0.0,
                }

        days_data = []
        current_date = start_date
        while current_date <= end_date:
            timer_list = all_timer_lists_by_date[current_date]
            work_start_ms, work_end_ms = _cnc_get_working_hours_for_date(current_date, tz_business)

            enriched_tasks = []
            enriched_hold_tasks = []
            for td in timer_list:
                task_key = td.get('task_key')
                info = task_info_map.get(task_key, {}) if task_key else {}
                enriched = {
                    "timer_id": td["timer_id"],
                    "start_time": td["start_time"],
                    "finish_time": td["finish_time"],
                    "task_key": task_key,
                    "task_name": td["task_name"],
                    "nesting_id": td["nesting_id"],
                    "material": td["material"],
                    "thickness_mm": td["thickness_mm"],
                    "parts_count": parts_map.get(task_key, 0) if task_key else 0,
                    "estimated_hours": info.get("estimated_hours"),
                    "total_hours_spent": info.get("total_hours_spent", 0.0),
                    "status": info.get("status"),
                    "completed_by": {
                        "id": info["completed_by_id"],
                        "username": info["completed_by_username"],
                        "first_name": info["completed_by_first_name"],
                        "last_name": info["completed_by_last_name"],
                    } if info.get("completed_by_id") else None,
                    "completion_date": info.get("completion_date"),
                    "duration_minutes": td["duration_minutes"],
                    "comment": td["comment"],
                    "machine_name": td["machine_name"],
                    "manual_entry": td["manual_entry"],
                }
                task_obj = td.get("_task_obj")
                if task_obj and getattr(task_obj, 'is_hold_task', False):
                    enriched_hold_tasks.append(enriched)
                else:
                    enriched_tasks.append(enriched)

            idle_periods = _cnc_calculate_idle_periods(timer_list, work_start_ms, work_end_ms, now_ms)

            if enriched_tasks or enriched_hold_tasks or idle_periods:
                days_data.append({
                    "date": current_date.isoformat(),
                    "tasks": enriched_tasks,
                    "hold_tasks": enriched_hold_tasks,
                    "idle_periods": idle_periods,
                })

            current_date += timedelta(days=1)

        return Response({
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days_data,
        }, status=200)
