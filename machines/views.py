from config.settings import TELEGRAM_MAINTENANCE_BOT_TOKEN
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
import requests

from machines.models import Machine, MachineFault
from machines.serializers import MachineFaultSerializer, MachineGetSerializer, MachineListSerializer, MachineSerializer
from users.permissions import IsAdmin
from django.db.models import Q

# Create your views here.

class MachineListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

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

    def post(self, request):
        serializer = MachineSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    
class MachineDetailView(APIView):
    def get_permissions(self):
        if self.request.method in ['POST', 'PATCH', 'PUT']:
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]

    def get_object(self, pk):
        return get_object_or_404(Machine, pk=pk)

    def get(self, request, pk):
        machine = self.get_object(pk)
        serializer = MachineGetSerializer(machine)
        return Response(serializer.data)

    def put(self, request, pk):
        machine = self.get_object(pk)
        serializer = MachineSerializer(machine, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def patch(self, request, pk):
        machine = self.get_object(pk)
        serializer = MachineSerializer(machine, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        machine = self.get_object(pk)
        machine.delete()
        return Response({"detail": "Machine deleted successfully."}, status=200)
    
class MachineTypeChoicesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in Machine.MACHINE_TYPES
        ])
    
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
            fault = serializer.save(reported_by=request.user)
            self.send_telegram_notification(fault, request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    

    def send_telegram_notification(self, fault, user):
        CHAT_ID = "-4944950975"

        reported_at = timezone.localtime(fault.reported_at).strftime("%d.%m.%Y %H:%M")
        machine_name = fault.machine.name if fault.machine else "Bilinmiyor"
        description = fault.description or "Yok"
        talep_eden = user.get_full_name() or user.username
        message = f"""🛠 *Yeni Bakım Talebi*
            👤 *Talep Eden:* {talep_eden}
            🖥 *Makine:* {machine_name}  
            📄 *Açıklama:* {description}  
            📅 *Tarih:* {reported_at}
        """

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }

        try:
            requests.post(url, data=payload, timeout=5)
        except requests.RequestException as e:
            print("Telegram bildirim hatası:", e)

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
                updated_fault = serializer.save(
                    resolved_by=request.user,
                    resolved_at=timezone.now()
                )
                self.send_resolution_notification(updated_fault, request.user)
            else:
                serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        fault = self.get_object(pk)
        fault.delete()
        return Response(status=204)
    
    def send_resolution_notification(self, fault, user):
        CHAT_ID = "-4944950975"

        resolved_at = timezone.localtime(fault.resolved_at).strftime("%d.%m.%Y %H:%M")
        machine_name = fault.machine.name if fault.machine else "Bilinmiyor"
        description = fault.resolution_description or "Yok"
        resolved_by = user.get_full_name() or user.username

        message = f"""✅ *Bakım Talebi Çözüldü*
            👤 *Çözen:* {resolved_by}
            🖥 *Makine:* {machine_name}
            📄 *Açıklama:* {description}
            📅 *Çözüm Tarihi:* {resolved_at}
        """

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }

        try:
            requests.post(url, data=payload, timeout=5)
        except requests.RequestException as e:
            print("Telegram çözüm bildirimi hatası:", e)