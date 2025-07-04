import time
from rest_framework.response import Response
from django.db.models import F, Sum, ExpressionWrapper, FloatField
from machining.filters import TaskFilter
from machining.permissions import MachiningProtectedView
from users.permissions import IsAdmin, IsMachiningUserOrAdmin
from .models import Task, Timer
from .serializers import TaskSerializer, TimerSerializer
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.generics import RetrieveUpdateDestroyAPIView
from rest_framework.viewsets import ModelViewSet
from django_filters.rest_framework import DjangoFilterBackend

class TimerStartView(MachiningProtectedView):
    def post(self, request):
        data = request.data.copy()
        data["manual_entry"] = False
        serializer = TimerSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            timer = serializer.save()
            return Response({"id": timer.id}, status=200)
        return Response(serializer.errors, status=400)

class TimerStopView(MachiningProtectedView):
    def post(self, request):
        timer_id = request.data.get("timer_id")
        try:
            timer = Timer.objects.get(id=timer_id)
            is_admin = request.user.is_superuser or getattr(request.user, "is_admin", False)

            if not is_admin and timer.user != request.user:
                return Response("Permission denied for this timer.", status=403)

            was_running = timer.finish_time is None
            finish_time_from_request = request.data.get("finish_time")

            # Update allowed fields
            for field in ['finish_time', 'comment', 'synced_to_jira', 'machine']:
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

        # Optional filtering by active/inactive timers
        if request.GET.get("is_active") == "true":
            query &= Q(finish_time__isnull=True)
        elif request.GET.get("is_active") == "false":
            query &= Q(finish_time__isnull=False)

        profile = getattr(request.user, 'profile', None)
        is_admin = request.user.is_superuser or getattr(profile, "is_admin", False)

        user_param = request.GET.get("user")
        if is_admin:
            if user_param:
                query &= Q(user__username=user_param)
        else:
            query &= Q(user=request.user)

        # Optional issue_key filter
        if "issue_key" in request.GET:
            query &= Q(issue_key=request.GET["issue_key"])

        # ✅ Optional start_time range filter (timestamps in seconds or ms)
        start_after = request.GET.get("start_after")
        start_before = request.GET.get("start_before")

        if start_after:
            try:
                start_after_ts = int(start_after)
                if start_after_ts < 1_000_000_000_000:  # if seconds, convert to ms
                    start_after_ts *= 1000
                query &= Q(start_time__gte=start_after_ts)
            except ValueError:
                return Response({"error": "Invalid start_after timestamp"}, status=400)

        if start_before:
            try:
                start_before_ts = int(start_before)
                if start_before_ts < 1_000_000_000_000:  # if seconds, convert to ms
                    start_before_ts *= 1000
                query &= Q(start_time__lte=start_before_ts)
            except ValueError:
                return Response({"error": "Invalid start_before timestamp"}, status=400)

        # ✅ Optional job_no filter (exact match)
        if "job_no" in request.GET:
            query &= Q(job_no=request.GET["job_no"])

        timers = Timer.objects.filter(query).order_by(ordering)
        return Response(TimerSerializer(timers, many=True).data)


class TimerDetailView(RetrieveUpdateDestroyAPIView):
    queryset = Timer.objects.all()
    serializer_class = TimerSerializer
    permission_classes = [IsMachiningUserOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or (hasattr(user, 'profile') and user.profile.is_admin):
            return Timer.objects.all()
        return Timer.objects.filter(user=user)

    def perform_update(self, serializer):
        serializer.save(stopped_by=self.request.user if self.request.data.get("finish_time") else serializer.instance.stopped_by)

    def destroy(self, request, *args, **kwargs):
        user = request.user
        is_admin = user.is_superuser or (hasattr(user, 'profile') and user.profile.is_admin)

        if not is_admin:
            return Response({"error": "You are not allowed to delete this timer."}, status=403)

        return super().destroy(request, *args, **kwargs)


class TimerReportView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        # Optional query params
        group_by = request.query_params.get('group_by', 'user')  # user, machine, job_no
        synced_only = request.query_params.get('synced_only') == 'true'
        manual_only = request.query_params.get('manual_only') == 'true'
        start_after = request.query_params.get('start_after')
        start_before = request.query_params.get('start_before')

        # Valid group_by fields
        valid_groups = {
            'user': 'user__username',
            'machine': 'machine',
            'job_no': 'issue_key__job_no',
            'issue_key': 'issue_key',
        }
        group_field = valid_groups.get(group_by)
        if not group_field:
            return Response({'error': 'Invalid group_by value'}, status=400)

        # Base queryset
        timers = Timer.objects.all()

        # Filters
        if synced_only:
            timers = timers.filter(synced_to_jira=True)
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
            .annotate(total_hours=Sum(duration_expr))
            .annotate(group=F(group_field))  # flatten to 'group'
            .values('group', 'total_hours')
            .order_by('group')
        )

        return Response(report)
    


class TaskViewSet(ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsMachiningUserOrAdmin]
    filterset_class = TaskFilter


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
