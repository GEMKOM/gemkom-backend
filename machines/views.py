from django.conf import settings
from config.settings import TELEGRAM_MAINTENANCE_BOT_TOKEN
from machines.calendar import DEFAULT_WEEK_TEMPLATE
from machines.filters import MachineFilter
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
import requests

from machines.models import Machine, MachineCalendar, MachineFault
from machines.serializers import MachineCalendarSerializer, MachineFaultSerializer, MachineGetSerializer, MachineListSerializer, MachineSerializer
from machining.models import Timer
from users.permissions import IsAdmin, IsMachiningUserOrAdmin
from django.db.models import Q, Count, Sum, DecimalField, Value
from django.db.models.functions import Coalesce

# Create your views here.

from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

class MachineListCreateView(generics.ListCreateAPIView):
    queryset = Machine.objects.all().order_by('id')
    serializer_class = MachineListSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MachineFilter
    filterset_fields = ["used_in", "is_active", "machine_type", "assigned_users"]  # <- filter by user id
    search_fields = ["name", "code"]  # <- search by code too
    ordering_fields = ["id", "name", "machine_type", "code"]
    ordering = ['id']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated(), IsAdmin()]
        return [permissions.IsAuthenticated()]
    
    def get(self, request):
        query = Q()
        used_in = request.GET.get("used_in")
        is_active = request.GET.get("is_active")
        if used_in:
            query &= Q(used_in=used_in)
        if is_active:
            query &= Q(is_active=is_active)


        not_completed = Q(machine_tasks__completion_date__isnull=True)
        dec_field = DecimalField(max_digits=12, decimal_places=2) 
        machines = (
            Machine.objects
            .filter(query)
            .annotate(
                tasks_count=Count(
                    'machine_tasks',
                    filter=not_completed  # only NOT completed
                ),
                total_estimated_hours=Sum(
                    Coalesce('machine_tasks__estimated_hours',
                            Value(0, output_field=dec_field)),
                    filter=not_completed,
                    output_field=dec_field,
)
            )
            .order_by('-machine_type')
        )
        serializer = MachineListSerializer(machines, many=True)
        return Response(serializer.data)
    
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
    
class UsedInChoicesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in Machine.USED_IN_CHOICES
        ])
    
class MachineFaultListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = Q()
        user = request.user
        profile = getattr(user, 'profile', None)

        # Restrict non-admin, non-maintenance users to their own faults
        if not user.is_admin and getattr(profile, 'team', '') != 'maintenance':
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

                # ✅ Stop active timers if it's a breaking fault
                if updated_fault.is_breaking and updated_fault.machine:
                    active_timers = Timer.objects.filter(machine_fk=updated_fault.machine, finish_time__isnull=True)
                    for timer in active_timers:
                        timer.finish_time = int(timezone.now().timestamp() * 1000)
                        timer.stopped_by = request.user
                        timer.save()

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


class MachineCalendarView(APIView):
    """
    GET /machining/planning/calendar?machine_fk=5
    PUT /machining/planning/calendar?machine_fk=5
      body: {
        "timezone": "Europe/Istanbul",   // optional
        "week_template": { "0":[...], ..., "6":[...] },
        "work_exceptions": [ {"date":"YYYY-MM-DD","windows":[...], "note":"..."} ]
      }
    """
    permission_classes = [IsMachiningUserOrAdmin]

    def get(self, request):
        machine_id = request.query_params.get("machine_fk")
        if not machine_id:
            return Response({"error": "machine_fk is required"}, status=400)
        try:
            m = Machine.objects.get(pk=machine_id)
        except Machine.DoesNotExist:
            return Response({"error": "machine not found"}, status=404)

        cal = getattr(m, "calendar", None)
        if cal is None:
            # serve defaults when no calendar exists yet
            return Response({
                "machine_id": m.id,
                "timezone": getattr(settings, "APP_DEFAULT_TZ", "Europe/Istanbul"),
                "week_template": DEFAULT_WEEK_TEMPLATE,
                "work_exceptions": [],
                "is_default": True
            }, status=200)

        data = {
            "machine_id": m.id,
            "timezone": cal.timezone or getattr(settings, "APP_DEFAULT_TZ", "Europe/Istanbul"),
            "week_template": cal.week_template or DEFAULT_WEEK_TEMPLATE,
            "work_exceptions": cal.work_exceptions or [],
            "is_default": False
        }
        return Response(data, status=200)

    def put(self, request):
        machine_id = request.query_params.get("machine_fk")
        if not machine_id:
            return Response({"error": "machine_fk is required"}, status=400)
        try:
            m = Machine.objects.get(pk=machine_id)
        except Machine.DoesNotExist:
            return Response({"error": "machine not found"}, status=404)

        cal, _ = MachineCalendar.objects.get_or_create(machine_fk=m)
        ser = MachineCalendarSerializer(instance=cal, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        out = {
            "machine_id": m.id,
            "timezone": cal.timezone,
            "week_template": cal.week_template or DEFAULT_WEEK_TEMPLATE,
            "work_exceptions": cal.work_exceptions or [],
            "is_default": False
        }
        return Response(out, status=200)