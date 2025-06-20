from rest_framework import generics, status
from rest_framework.response import Response
from machining.permissions import MachiningProtectedView
from .models import Timer
from .serializers import TimerSerializer
from django.db.models import Q

class TimerStartView(MachiningProtectedView):
    def post(self, request):
        data = request.data.copy()
        data["manual_entry"] = False
        serializer = TimerSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({"id": serializer.data['id']}, status=200)
        return Response(serializer.errors, status=400)

class TimerStopView(MachiningProtectedView):
    def post(self, request):
        timer_id = request.data.get("timer_id")
        try:
            timer = Timer.objects.get(id=timer_id)
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
        serializer = TimerSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response({"id": serializer.data['id']}, status=200)
        return Response(serializer.errors, status=400)

class TimerListView(MachiningProtectedView):
    def get(self, request):
        query = Q()
        if request.GET.get("is_active") == "true":
            query &= Q(finish_time__isnull=True)
        elif request.GET.get("is_active") == "false":
            query &= Q(finish_time__isnull=False)
        if "user" in request.GET:
            query &= Q(user__username=request.GET["user"])
        if "issue_key" in request.GET:
            query &= Q(issue_key=request.GET["issue_key"])

        timers = Timer.objects.filter(query).order_by("-start_time")
        return Response(TimerSerializer(timers, many=True).data)


