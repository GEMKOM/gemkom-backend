import time
import logging
from django.db import transaction
from django.utils import timezone
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter

from .models import LinearCuttingSession, LinearCuttingPart, LinearCuttingTask
from .serializers import (
    LinearCuttingSessionListSerializer,
    LinearCuttingSessionDetailSerializer,
    LinearCuttingPartSerializer,
    LinearCuttingTaskListSerializer,
    LinearCuttingTaskDetailSerializer,
    LinearCuttingTimerSerializer,
)
from .optimizer import optimize
from .pdf import build_cutting_list_pdf
from tasks.views import (
    GenericTimerStartView,
    GenericTimerStopView,
    GenericTimerManualEntryView,
    GenericTimerListView,
    GenericTimerDetailView,
    GenericMarkTaskCompletedView,
    GenericUnmarkTaskCompletedView,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Session ViewSet
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingSessionViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return LinearCuttingSession.objects.prefetch_related('parts').all()

    def get_serializer_class(self):
        if self.action == 'list':
            return LinearCuttingSessionListSerializer
        return LinearCuttingSessionDetailSerializer


# ─────────────────────────────────────────────────────────────────────────────
# Optimize endpoint
# ─────────────────────────────────────────────────────────────────────────────

class OptimizeView(APIView):
    """
    POST /linear_cutting/sessions/{key}/optimize/

    Runs the FFD bin-packing algorithm on the session's parts and stores
    the result in the session.  Optionally overrides stock_length_mm / kerf_mm.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        try:
            session = LinearCuttingSession.objects.prefetch_related('parts').get(key=key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        stock_length_mm = int(request.data.get('stock_length_mm', session.stock_length_mm))
        kerf_mm = float(request.data.get('kerf_mm', session.kerf_mm))

        parts_qs = session.parts.all()
        if not parts_qs.exists():
            return Response({'error': 'Session has no parts. Add parts before optimizing.'}, status=status.HTTP_400_BAD_REQUEST)

        parts_data = [
            {
                'id': p.id,
                'label': p.label,
                'job_no': p.job_no,
                'nominal_length_mm': p.nominal_length_mm,
                'quantity': p.quantity,
                'angle_left_deg': float(p.angle_left_deg),
                'angle_right_deg': float(p.angle_right_deg),
                'profile_height_mm': p.profile_height_mm,
            }
            for p in parts_qs
        ]

        try:
            result = optimize(parts_data, stock_length_mm, kerf_mm)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # Persist result on the session
        session.stock_length_mm = stock_length_mm
        session.kerf_mm = kerf_mm
        session.bars_needed = result['bars_needed']
        session.total_waste_mm = result['total_waste_mm']
        session.efficiency_pct = result['efficiency_pct']
        session.optimization_result = result
        session.save(update_fields=[
            'stock_length_mm', 'kerf_mm',
            'bars_needed', 'total_waste_mm', 'efficiency_pct', 'optimization_result',
        ])

        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# Confirm endpoint — create tasks + planning request
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmView(APIView):
    """
    POST /linear_cutting/sessions/{key}/confirm/

    Creates one LinearCuttingTask per bar from the optimization result,
    and one PlanningRequest for the raw stock needed.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        try:
            session = LinearCuttingSession.objects.prefetch_related('parts').get(key=key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not session.optimization_result:
            return Response(
                {'error': 'Run /optimize/ before confirming.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tasks_already = session.tasks_created
        pr_already = session.planning_request_created

        if tasks_already and pr_already:
            return Response({'error': 'Tasks and planning request already created for this session.'}, status=status.HTTP_409_CONFLICT)

        result = session.optimization_result

        with transaction.atomic():
            created_task_keys = []

            if not tasks_already:
                for bar in result['bars']:
                    task_key = f"{session.key}-B{bar['bar_index']}"
                    task, _ = LinearCuttingTask.objects.get_or_create(
                        key=task_key,
                        defaults={
                            'session': session,
                            'bar_index': bar['bar_index'],
                            'stock_length_mm': bar['stock_length_mm'],
                            'material': session.material,
                            'layout_json': bar['cuts'],
                            'waste_mm': bar['waste_mm'],
                            'name': f"{session.title} – Bar {bar['bar_index']}",
                            'quantity': 1,
                            'created_by': request.user,
                            'created_at': int(time.time() * 1000),
                        }
                    )
                    created_task_keys.append(task_key)
                session.tasks_created = True

            planning_request_number = None
            if not pr_already:
                from planning.models import PlanningRequest, PlanningRequestItem
                from procurement.models import Item

                needed_date = request.data.get('needed_date') or str(timezone.localdate())
                priority = request.data.get('priority', 'normal')

                pr = PlanningRequest(
                    title=f"Linear Cutting Stock – {session.key} {session.title}",
                    description=(
                        f"Raw stock bars required for linear cutting session {session.key}.\n"
                        f"Material: {session.material}, Stock length: {session.stock_length_mm} mm, "
                        f"Bars needed: {result['bars_needed']}"
                    ),
                    needed_date=needed_date,
                    created_by=request.user,
                    priority=priority,
                    check_inventory=False,
                )
                pr.save()
                planning_request_number = pr.request_number

                # Build one line per distinct (material, stock_length_mm) combination
                # — in practice the session has one material/length, but we're future-proof.
                from collections import defaultdict
                combo_counts = defaultdict(int)
                for bar in result['bars']:
                    combo_counts[(session.material, bar['stock_length_mm'])] += 1

                # Try to find or create a matching Item in the catalog
                for (material, length_mm), qty in combo_counts.items():
                    item_code = f"RAW-{material.replace(' ', '-').upper()}-{length_mm}"
                    item_name = f"{material} {length_mm} mm"
                    item, _ = Item.objects.get_or_create(
                        code=item_code,
                        defaults={
                            'name': item_name,
                            'unit': 'adet',
                            'item_type': 'stock',
                        }
                    )

                    # Collect job numbers from parts
                    job_nos = list(
                        session.parts.exclude(job_no='')
                        .values_list('job_no', flat=True)
                        .distinct()
                    )
                    job_no_str = ', '.join(job_nos) if job_nos else ''

                    PlanningRequestItem.objects.create(
                        planning_request=pr,
                        item=item,
                        job_no=job_no_str,
                        quantity=qty,
                        quantity_to_purchase=qty,
                        item_description=item_name,
                        specifications=(
                            f"Linear cutting session: {session.key}. "
                            f"Kerf: {session.kerf_mm} mm."
                        ),
                        order=1,
                    )

                session.planning_request_created = True

            session.save(update_fields=['tasks_created', 'planning_request_created'])

        return Response({
            'created_tasks': created_task_keys,
            'planning_request_number': planning_request_number,
            'tasks_already_existed': tasks_already,
            'planning_request_already_existed': pr_already,
        })


# ─────────────────────────────────────────────────────────────────────────────
# PDF endpoint
# ─────────────────────────────────────────────────────────────────────────────

class CuttingListPDFView(APIView):
    """
    GET /linear_cutting/sessions/{key}/pdf/

    Returns a printable A4 PDF cutting list for the session.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        try:
            session = LinearCuttingSession.objects.prefetch_related('parts').get(key=key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not session.optimization_result:
            return Response(
                {'error': 'Run /optimize/ before generating a PDF.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pdf_bytes = build_cutting_list_pdf(session)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{session.key}_cutting_list.pdf"'
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Parts ViewSet (manage parts independently of session creation)
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingPartViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LinearCuttingPartSerializer

    def get_queryset(self):
        qs = LinearCuttingPart.objects.all()
        session_key = self.request.query_params.get('session')
        if session_key:
            qs = qs.filter(session__key=session_key)
        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Task ViewSet
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingTaskViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['created_at', 'completion_date', 'bar_index']

    def get_queryset(self):
        qs = LinearCuttingTask.objects.select_related('session', 'machine_fk').prefetch_related('issue_key')
        session_key = self.request.query_params.get('session')
        if session_key:
            qs = qs.filter(session__key=session_key)
        completed = self.request.query_params.get('completed')
        if completed == 'true':
            qs = qs.exclude(completion_date__isnull=True)
        elif completed == 'false':
            qs = qs.filter(completion_date__isnull=True)
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return LinearCuttingTaskListSerializer
        return LinearCuttingTaskDetailSerializer


# ─────────────────────────────────────────────────────────────────────────────
# Timer views (thin wrappers over generic views)
# ─────────────────────────────────────────────────────────────────────────────

class TimerStartView(GenericTimerStartView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='linear_cutting')


class TimerStopView(GenericTimerStopView):
    permission_classes = [IsAuthenticated]


class TimerManualEntryView(GenericTimerManualEntryView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='linear_cutting')


class TimerListView(GenericTimerListView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='linear_cutting')


class TimerDetailView(GenericTimerDetailView):
    permission_classes = [IsAuthenticated]


# ─────────────────────────────────────────────────────────────────────────────
# Mark completed / uncompleted
# ─────────────────────────────────────────────────────────────────────────────

class MarkTaskCompletedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='linear_cutting')


class UnmarkTaskCompletedView(GenericUnmarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='linear_cutting')
