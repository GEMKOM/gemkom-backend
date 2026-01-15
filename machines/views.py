from django.conf import settings
from config.settings import TELEGRAM_MAINTENANCE_BOT_TOKEN
from machines.calendar import DEFAULT_WEEK_TEMPLATE
from machines.filters import MachineFaultFilter, MachineFilter
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.utils import timezone
import requests

from machines.models import Machine, MachineCalendar, MachineFault
from machines.serializers import MachineCalendarSerializer, MachineFaultSerializer, MachineGetSerializer, MachineListSerializer, MachineMinimalSerializer, MachineSerializer
from tasks.models import Timer
from users.permissions import IsAdmin, IsMachiningUserOrAdmin
from django.db.models import Q

from config.pagination import CustomPageNumberPagination

# Create your views here.

from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

class MachineListCreateView(generics.ListCreateAPIView):
    queryset = Machine.objects.all().order_by('id')
    serializer_class = MachineListSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MachineFilter
    filterset_fields = ["used_in", "is_active", "machine_type", "assigned_users"]
    search_fields = ["name", "code"]
    ordering_fields = ["id", "name", "machine_type", "code"]
    ordering = ['id']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated(), IsAdmin()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.request.query_params.get("compact") == "true":
            return MachineMinimalSerializer
        return MachineListSerializer

    def get_queryset(self):
        # Compact path: super lightweight list (no annotations), is_active=True
        if self.request.query_params.get("compact") == "true":
            qs = (Machine.objects
                  .filter(is_active=True)
                  .only("id", "name", "code", "used_in")
                  .order_by("name"))
            # filters/search/order still work because fields exist on the model
            return qs

        # Full path: keep your current annotated queryset
        from django.db.models import DecimalField, Q, Value
        from django.db.models.functions import Coalesce
        from django.db.models import Count, Sum

        dec_field = DecimalField(max_digits=12, decimal_places=2)
        machining_not_completed = Q(machining_task_related__completion_date__isnull=True)
        cnc_not_completed = Q(cnc_tasks__completion_date__isnull=True)

        qs = Machine.objects.all()
        return (
            qs.annotate(
                tasks_count=Count('machining_task_related', filter=machining_not_completed) + Count('cnc_tasks', filter=cnc_not_completed),
                total_estimated_hours=Sum(
                    Coalesce('machining_task_related__estimated_hours', Value(0, output_field=dec_field)),
                    filter=machining_not_completed,
                    output_field=dec_field,
                ) + Sum(
                    Coalesce('cnc_tasks__estimated_hours', Value(0, output_field=dec_field)),
                    filter=cnc_not_completed,
                    output_field=dec_field,
                ),
            )
            .order_by('-machine_type')
        )
    
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


class MachineDropdownView(APIView):
    """
    Ultra-lightweight endpoint for machine dropdowns.
    Returns only id, name, and used_in for all active machines.
    Optionally filter by used_in query parameter.
    Optionally include availability flags with include_availability=true.

    GET /machines/dropdown/
    GET /machines/dropdown/?used_in=machining
    GET /machines/dropdown/?include_availability=true
    GET /machines/dropdown/?used_in=machining&include_availability=true
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from machines.serializers import MachineDropdownSerializer

        queryset = Machine.objects.filter(is_active=True).only('id', 'name', 'used_in').order_by('name')

        # Optional filter by used_in
        used_in = request.query_params.get('used_in')
        if used_in:
            queryset = queryset.filter(used_in=used_in)

        # Check if availability flags are requested
        include_availability = request.query_params.get('include_availability', '').lower() == 'true'

        if include_availability:
            # Build enriched response with availability flags
            results = []
            for machine in queryset:
                # Check for active timers
                has_active_timer = Timer.objects.filter(
                    machine_fk=machine,
                    finish_time__isnull=True
                ).exists()

                # Check for unresolved breaking faults
                is_under_maintenance = MachineFault.objects.filter(
                    machine=machine,
                    resolved_at__isnull=True,
                    is_breaking=True
                ).exists()

                results.append({
                    'id': machine.id,
                    'name': machine.name,
                    'used_in': machine.used_in,
                    'is_available': not (has_active_timer or is_under_maintenance),
                    'has_active_timer': has_active_timer,
                    'is_under_maintenance': is_under_maintenance
                })
            return Response(results)
        else:
            # Standard lightweight response
            serializer = MachineDropdownSerializer(queryset, many=True)
            return Response(serializer.data)


class MachineFaultListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MachineFaultSerializer
    pagination_class = CustomPageNumberPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MachineFaultFilter
    # keep your original simple filters too (redundant but harmless with filterset_class)
    filterset_fields = ["machine", "reported_by"]

    # Expanded search to cover fallback fields + machine name/code
    search_fields = ["description", "asset_name", "location", "machine__name", "machine__code"]

    ordering_fields = ["reported_at", "id", "resolved_at", "is_breaking", "is_maintenance"]
    ordering = ["-reported_at"]

    def get_queryset(self):
        user = self.request.user
        profile = getattr(user, 'profile', None)

        query = Q()
        # Restrict non-admin, non-maintenance users to their own faults
        if not getattr(user, "is_admin", False) and getattr(profile, "team", "") != "maintenance":
            query &= Q(reported_by=user)

        # Backwards-compat: still honor ?machine_id=... (also provided by filterset_class)
        machine_id = self.request.query_params.get("machine_id")
        if machine_id:
            query &= Q(machine_id=machine_id)

        return (
            MachineFault.objects
            .filter(query)
            .select_related("machine", "reported_by", "resolved_by", "assigned_to")
        )

    def perform_create(self, serializer):
        now_ms = int(timezone.now().timestamp() * 1000)

        # Set downtime start if this is a breaking fault
        if serializer.validated_data.get('is_breaking'):
            fault = serializer.save(
                reported_by=self.request.user,
                downtime_start_ms=now_ms
            )
        else:
            fault = serializer.save(reported_by=self.request.user)

        # Auto-create downtime timers if this is a breaking fault
        if fault.is_breaking and fault.machine:
            self._create_downtime_timers_for_fault(fault)

        self.send_telegram_notification(fault, self.request.user)

    def _create_downtime_timers_for_fault(self, fault):
        """
        When a breaking fault is reported, automatically:
        1. Stop all active productive timers on this machine
        2. Start downtime timers linked to the fault
        """
        from tasks.models import Timer, DowntimeReason

        now_ms = int(timezone.now().timestamp() * 1000)

        # Get or create the "Machine Issue" downtime reason
        machine_issue_reason, _ = DowntimeReason.objects.get_or_create(
            code='MACHINE_FAULT',
            defaults={
                'name': 'Machine Issue',
                'category': 'downtime',
                'creates_timer': True,
                'requires_fault_reference': True,
                'display_order': 10
            }
        )

        # Find all active productive timers on this machine
        active_timers = Timer.objects.filter(
            machine_fk=fault.machine,
            finish_time__isnull=True,
            timer_type='productive'
        ).select_related('user', 'content_type')

        for timer in active_timers:
            # Stop the productive timer
            timer.finish_time = now_ms
            timer.stopped_by = self.request.user
            timer.save(update_fields=['finish_time', 'stopped_by'])

            # Start a downtime timer for the same operation/task
            Timer.objects.create(
                user=timer.user,
                start_time=now_ms,
                machine_fk=fault.machine,
                content_type=timer.content_type,
                object_id=timer.object_id,
                timer_type='downtime',
                downtime_reason=machine_issue_reason,
                related_fault=fault,
                comment=f'Auto-created due to machine fault: {fault.description[:100]}'
            )

    def _stop_downtime_timers_for_fault(self, fault, user):
        """
        When a fault is resolved, stop all downtime timers linked to this fault.
        Operators can then manually start new productive timers when ready to resume work.
        """
        from tasks.models import Timer

        now_ms = int(timezone.now().timestamp() * 1000)

        # Find all active downtime timers related to this fault
        downtime_timers = Timer.objects.filter(
            related_fault=fault,
            finish_time__isnull=True,
            timer_type='downtime'
        )

        for timer in downtime_timers:
            timer.finish_time = now_ms
            timer.stopped_by = user
            timer.save(update_fields=['finish_time', 'stopped_by'])

    # --- Notifications ---
    def send_telegram_notification(self, fault: MachineFault, user):
        if not TELEGRAM_MAINTENANCE_BOT_TOKEN:
            return  # quietly skip if token not configured

        CHAT_ID = "-4944950975"  # your group/chat

        reported_at = timezone.localtime(fault.reported_at).strftime("%d.%m.%Y %H:%M")
        machine_name = fault.machine.name if fault.machine else (fault.asset_name or "Bilinmiyor")
        description = fault.description or "Yok"
        talep_eden = user.get_full_name() or user.username

        message = (
            "🛠 *Yeni Bakım Talebi*\n"
            f"👤 *Talep Eden:* {talep_eden}\n"
            f"🖥 *Makine:* {machine_name}\n"
            f"📄 *Açıklama:* {description}\n"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, data=payload, timeout=5)
        except requests.RequestException as e:
            print("Telegram bildirim hatası:", e)


class MachineFaultDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk):
        return get_object_or_404(
            MachineFault.objects.select_related("machine", "reported_by", "resolved_by", "assigned_to"), pk=pk
        )

    def get(self, request, pk):
        fault = self.get_object(pk)
        serializer = MachineFaultSerializer(fault)
        return Response(serializer.data)

    def _stop_downtime_timers_for_fault(self, fault, user):
        """
        When a fault is resolved, stop all downtime timers linked to this fault.
        """
        from tasks.models import Timer

        now_ms = int(timezone.now().timestamp() * 1000)

        downtime_timers = Timer.objects.filter(
            related_fault=fault,
            finish_time__isnull=True,
            timer_type='downtime'
        )

        for timer in downtime_timers:
            timer.finish_time = now_ms
            timer.stopped_by = user
            timer.save(update_fields=['finish_time', 'stopped_by'])

    def put(self, request, pk):
        """
        Your current semantics:
        - If the fault is not resolved yet, a PUT marks it resolved (stamps resolved_by/at),
          then stops active timers on that machine if it's a breaking fault.
        - If already resolved, allow partial updates without touching resolution fields.
        - Only maintenance team members or admins can resolve faults.
        """
        fault = self.get_object(pk)
        serializer = MachineFaultSerializer(fault, data=request.data, partial=True)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        if not fault.resolved_at:
            # Only maintenance team or admins can resolve faults
            user_profile = getattr(request.user, 'profile', None)
            user_team = getattr(user_profile, 'team', None) if user_profile else None
            is_maintenance = user_team == 'maintenance'
            is_admin = request.user.is_superuser or getattr(request.user, 'is_admin', False)

            if not is_maintenance and not is_admin:
                return Response(
                    {'error': 'Only maintenance team members can resolve machine faults.'},
                    status=403
                )
            now_ms = int(timezone.now().timestamp() * 1000)

            # Set downtime end if this is a breaking fault
            if fault.is_breaking:
                updated_fault = serializer.save(
                    resolved_by=request.user,
                    resolved_at=timezone.now(),
                    downtime_end_ms=now_ms
                )
            else:
                updated_fault = serializer.save(
                    resolved_by=request.user,
                    resolved_at=timezone.now()
                )

            # Stop downtime timers linked to this fault
            if updated_fault.is_breaking and updated_fault.machine:
                self._stop_downtime_timers_for_fault(updated_fault, request.user)

            self.send_resolution_notification(updated_fault, request.user)
        else:
            serializer.save()

        return Response(serializer.data)

    def delete(self, request, pk):
        fault = self.get_object(pk)

        # Superusers can delete anything.
        # Other users can only delete faults they reported, and only if the fault is not yet resolved.
        can_delete = request.user.is_superuser or (
            fault.reported_by == request.user and not fault.resolved_at
        )

        if not can_delete:
            return Response(
                {"detail": "You do not have permission to delete this fault report. It may be resolved or you are not the reporter."},
                status=403
            )
        
        # If the fault is not yet resolved, send a cancellation notification.
        if not fault.resolved_at:
            self.send_cancellation_notification(fault, request.user)

        fault.delete()
        return Response(status=204)  # No Content

    # --- Notifications ---
    def send_cancellation_notification(self, fault: MachineFault, user):
        if not TELEGRAM_MAINTENANCE_BOT_TOKEN:
            return

        CHAT_ID = "-4944950975"

        machine_name = fault.machine.name if fault.machine else (fault.asset_name or "Bilinmiyor")
        description = fault.description or "Yok"
        cancelled_by = user.get_full_name() or user.username

        message = (
            "❌ *Bakım Talebi İptal Edildi*\n"
            f"👤 *İptal Eden:* {cancelled_by}\n"
            f"🖥 *Makine:* {machine_name}\n"
            f"📄 *Açıklama:* {description}\n"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, data=payload, timeout=5)
        except requests.RequestException as e:
            print("Telegram iptal bildirimi hatası:", e)

    def send_resolution_notification(self, fault: MachineFault, user):
        if not TELEGRAM_MAINTENANCE_BOT_TOKEN:
            return  # quietly skip if token not configured

        CHAT_ID = "-4944950975"

        resolved_at = timezone.localtime(fault.resolved_at).strftime("%d.%m.%Y %H:%M")
        machine_name = fault.machine.name if fault.machine else (fault.asset_name or "Bilinmiyor")
        description = fault.resolution_description or "Yok"
        resolved_by = user.get_full_name() or user.username

        message = (
            "✅ *Bakım Talebi Çözüldü*\n"
            f"👤 *Çözen:* {resolved_by}\n"
            f"🖥 *Makine:* {machine_name}\n"
            f"📄 *Açıklama:* {description}\n"
        )

        url = f"https://api.telegram.org/bot{TELEGRAM_MAINTENANCE_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
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