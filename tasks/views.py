from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from django.db.models import Q, F, ExpressionWrapper, FloatField, Sum, Avg, Count
from django.contrib.contenttypes.models import ContentType
from collections import defaultdict

# Create your views here.
from .models import Timer
from .serializers import BaseTimerSerializer
from config.pagination import CustomPageNumberPagination


def _get_task_model_from_type(task_type):
    if task_type == 'machining':
        from machining.models import Task
        return Task
    # Add other task types here in the future
    # elif task_type == 'cnc_cutting':
    #     from cnc_cutting.models import CncTask
    #     return CncTask
    return None

def get_timer_serializer_class(task_type):
    """Dynamically returns the appropriate timer serializer."""
    if task_type == 'machining':
        from machining.serializers import TimerSerializer
        return TimerSerializer
    # Add other types here in the future
    # elif task_type == 'cnc_cutting':
    #     from cnc_cutting.serializers import TimerSerializer
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
        response = super().post(request, task_type)
        if response.status_code == status.HTTP_200_OK:
            timer_id = response.data['id']
            Timer.objects.filter(id=timer_id).update(manual_entry=True)
        return response


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
        if request.user and request.user.is_staff: # Use is_staff for admin-like abilities
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
        if user.is_staff: # Use is_staff for admin-like abilities
            return Timer.objects.all()
        return Timer.objects.filter(user=user)

    def perform_update(self, serializer):
        # Automatically set stopped_by user if a timer is being finished
        if self.request.data.get("finish_time") and not serializer.instance.finish_time:
            serializer.save(stopped_by=self.request.user)
        else:
            serializer.save()

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_staff:
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