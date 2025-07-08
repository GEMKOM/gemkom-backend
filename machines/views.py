from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone

from machines.models import Machine, MachineFault
from machines.serializers import MachineFaultSerializer, MachineListSerializer, MachineSerializer
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
    
class MachineDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        serializer = MachineListSerializer(machine)
        return Response(serializer.data)
    
class MachineFaultListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = Q()
        user = request.user
        profile = getattr(user, 'profile', None)

        # Restrict non-admin, non-maintenance users to their own faults
        if not user.is_superuser and not getattr(profile, 'is_admin', False) and getattr(profile, 'team', '') != 'maintenance':
            query &= Q(reported_by=user)

        machine_id = request.GET.get("machine_id")
        if machine_id:
            query &= Q(machine=machine_id)

        faults = MachineFault.objects.filter(query)
        serializer = MachineFaultSerializer(faults, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = MachineFaultSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(reported_by=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class MachineFaultDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(MachineFault, pk=pk)

    def get(self, request, pk):
        fault = self.get_object(pk)
        serializer = MachineFaultSerializer(fault)
        return Response(serializer.data)

    def put(self, request, pk):
        fault = self.get_object(pk)
        serializer = MachineFaultSerializer(fault, data=request.data, partial=True)
        if serializer.is_valid():
            if not fault.resolved_at:
                serializer.save(
                    resolved_by=request.user,
                    resolved_at=timezone.now()
                )
            else:
                serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        fault = self.get_object(pk)
        fault.delete()
        return Response(status=204)