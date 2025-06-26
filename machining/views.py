from rest_framework.response import Response
from machining.permissions import MachiningProtectedView
from .models import Timer
from .serializers import TimerSerializer
from django.db.models import Q


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

        # Determine if user is admin/superuser
        is_admin = request.user.is_superuser or getattr(request.user, "is_admin", False)

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
