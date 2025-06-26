from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from machines.models import Machine
from machines.serializers import MachineListSerializer, MachineSerializer
from users.permissions import IsAdmin
from django.db.models import Q

# Create your views here.

class MachineCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]
    def post(self, request):
        serializer = MachineSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    
class MachineUpdateView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]
    def put(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        serializer = MachineSerializer(machine, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def patch(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        serializer = MachineSerializer(machine, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

class MachineListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        query = Q()
        used_in = request.GET.get("used_in")
        is_active = request.GET.get("is_active")
        if used_in:
            query &= Q(used_in=used_in)
        if is_active:
            query &= Q(is_active=is_active)
        machines = Machine.objects.filter(query).order_by("-machine_type")
        serializer = MachineListSerializer(machines, many=True)
        return Response(serializer.data)
    
