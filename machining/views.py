from rest_framework.response import Response
from django.db.models import F, Sum, ExpressionWrapper, FloatField
from machining.permissions import MachiningProtectedView
from users.permissions import IsAdmin
from .models import Timer
from .serializers import TimerSerializer
from django.db.models import Q
from rest_framework.views import APIView


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
            if not is_admin:
                if timer.user != request.user:
                    return Response("Permission denied for this timer.", status=403)

            for field in ['finish_time', 'comment', 'synced_to_jira', 'machine']:
                if field in request.data:
                    setattr(timer, field, request.data[field])

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
        query = Q()

        # Optional filtering by active/inactive timers
        if request.GET.get("is_active") == "true":
            query &= Q(finish_time__isnull=True)
        elif request.GET.get("is_active") == "false":
            query &= Q(finish_time__isnull=False)

        profile = getattr(request.user, 'profile', None)
        # Determine if user is admin/superuser
        is_admin = request.user.is_superuser or getattr(profile, "is_admin", False)

        user_param = request.GET.get("user")
        if is_admin:
            if user_param:
                query &= Q(user__username=user_param)
            # else: no user filtering, show all
        else:
            # Non-admins can only see their own timers
            query &= Q(user=request.user)

        # Optional issue_key filter
        if "issue_key" in request.GET:
            query &= Q(issue_key=request.GET["issue_key"])

        timers = Timer.objects.filter(query).order_by("-start_time")
        return Response(TimerSerializer(timers, many=True).data)


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
            'job_no': 'job_no',
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

        report = timers.values(group_field).annotate(
            total_hours=Sum(duration_expr)
        ).order_by(group_field)

        return Response(report)