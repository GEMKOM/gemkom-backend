import time
import logging
from collections import defaultdict
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
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
from .pdf import build_cutting_list_pdf, build_task_pdf
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

    Groups parts by (item_id, stock_length_mm) and runs FFD bin-packing
    separately for each group.  Result is stored on the session as:
        {"groups": [{item_id, item_name, item_code, stock_length_mm, kerf_mm,
                     bars_needed, total_waste_mm, efficiency_pct, bars: [...]}]}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        try:
            session = LinearCuttingSession.objects.prefetch_related(
                'parts', 'parts__item'
            ).get(key=key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        kerf_mm = float(request.data.get('kerf_mm', session.kerf_mm))

        parts_qs = list(session.parts.select_related('item').all())
        if not parts_qs:
            return Response(
                {'error': 'Session has no parts. Add parts before optimizing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check all parts have an item assigned
        parts_without_item = [p for p in parts_qs if not p.item_id]
        if parts_without_item:
            labels = ', '.join(f'"{p.label}"' for p in parts_without_item[:5])
            return Response(
                {'error': f'Some parts have no catalog item assigned: {labels}. Assign an item to every part before optimizing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Group parts by (item_id, effective stock_length_mm)
        # Each group key is (item_id, stock_length_mm_for_group)
        groups_map = defaultdict(list)
        for p in parts_qs:
            effective_stock = p.stock_length_mm or session.stock_length_mm
            groups_map[(p.item_id, effective_stock)].append(p)

        groups = []
        global_bar_index = 0

        for (item_id, stock_len), group_parts in groups_map.items():
            item_obj = group_parts[0].item
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
                for p in group_parts
            ]

            try:
                result = optimize(parts_data, stock_len, kerf_mm)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            # Assign global bar indices across all groups
            for bar in result['bars']:
                global_bar_index += 1
                bar['global_bar_index'] = global_bar_index

            groups.append({
                'item_id': item_id,
                'item_name': item_obj.name,
                'item_code': item_obj.code,
                'stock_length_mm': stock_len,
                'kerf_mm': kerf_mm,
                'bars_needed': result['bars_needed'],
                'total_waste_mm': result['total_waste_mm'],
                'efficiency_pct': result['efficiency_pct'],
                'bars': result['bars'],
            })

        optimization_result = {'groups': groups}

        session.kerf_mm = kerf_mm
        session.optimization_result = optimization_result
        session.save(update_fields=['kerf_mm', 'optimization_result'])

        return Response(optimization_result)


# ─────────────────────────────────────────────────────────────────────────────
# Confirm endpoint — create tasks + planning request
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmView(APIView):
    """
    POST /linear_cutting/sessions/{key}/confirm/

    Creates one LinearCuttingTask per bar (across all item groups) and one
    PlanningRequest with one PlanningRequestItem per (item × job_no) combination.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, key):
        try:
            session = LinearCuttingSession.objects.select_related(
                'planning_request'
            ).prefetch_related(
                'parts', 'parts__item'
            ).get(key=key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not session.optimization_result:
            return Response(
                {'error': 'Run /optimize/ before confirming.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        groups = session.optimization_result.get('groups', [])
        if not groups:
            return Response(
                {'error': 'Optimization result has no groups.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A planning request is considered "active" only if it exists and is not cancelled.
        # If the linked PR was cancelled (or the FK was cleared), allow re-creation.
        pr = session.planning_request
        pr_already = (
            pr is not None and
            getattr(pr, 'status', None) != 'cancelled'
        )

        if pr_already:
            return Response(
                {'error': 'Planning request already created for this session.'},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            created_task_keys = []

            # ── Tasks (always re-sync via get_or_create — idempotent) ──────
            for group in groups:
                item_id = group['item_id']
                item_name = group['item_name']
                for bar in group['bars']:
                    bar_idx = bar.get('global_bar_index', bar['bar_index'])
                    task_key = f"{session.key}-B{bar_idx}"
                    LinearCuttingTask.objects.get_or_create(
                        key=task_key,
                        defaults={
                            'session': session,
                            'item_id': item_id,
                            'bar_index': bar_idx,
                            'stock_length_mm': bar['stock_length_mm'],
                            'material': item_name,
                            'layout_json': bar['cuts'],
                            'waste_mm': bar['waste_mm'],
                            'name': f"{session.title} – {item_name} Bar {bar_idx}",
                            'quantity': 1,
                            'created_by': request.user,
                            'created_at': int(time.time() * 1000),
                        }
                    )
                    created_task_keys.append(task_key)
            session.tasks_created = True

            # ── Planning request ───────────────────────────────────────────
            planning_request_number = None
            if not pr_already:
                from planning.models import PlanningRequest, PlanningRequestItem
                from procurement.models import Item as ProcurementItem

                needed_date = request.data.get('needed_date') or str(timezone.localdate())
                priority = request.data.get('priority', 'normal')

                total_bars = sum(g['bars_needed'] for g in groups)

                pr = PlanningRequest(
                    title=f"Profil/Boru Kesim – {session.key} {session.title}",
                    description=(
                        f"Toplam {total_bars} çubuk, {len(groups)} farklı profil. "
                        f"Testere payı: {session.kerf_mm} mm."
                    ),
                    needed_date=needed_date,
                    created_by=request.user,
                    priority=priority,
                    check_inventory=True,
                )
                pr.save()
                planning_request_number = pr.request_number

                order_idx = 1
                for group in groups:
                    item_id = group['item_id']
                    item_obj = ProcurementItem.objects.get(pk=item_id)
                    stock_len = group['stock_length_mm']
                    stock_len_m = stock_len // 1000
                    item_unit = (item_obj.unit or '').lower()

                    # Map job_no → bars that contain a cut for this job_no in this group
                    bars_by_job_no: dict[str, int] = {}
                    for bar in group['bars']:
                        seen = set(cut['job_no'] for cut in bar['cuts'])
                        for jno in seen:
                            bars_by_job_no[jno] = bars_by_job_no.get(jno, 0) + 1

                    # Parts belonging to this exact group (item + stock_length_mm)
                    group_parts = session.parts.filter(
                        item_id=item_id,
                        stock_length_mm=stock_len,
                    )
                    # Also include parts with no stock_length_mm override when the
                    # group's stock_len equals the session default
                    if stock_len == session.stock_length_mm:
                        group_parts = session.parts.filter(
                            item_id=item_id,
                        ).filter(
                            Q(stock_length_mm=stock_len) | Q(stock_length_mm__isnull=True)
                        )
                    distinct_job_nos = list(
                        group_parts.values_list('job_no', flat=True).distinct()
                    )

                    for job_no in distinct_job_nos:
                        parts_for_job = group_parts.filter(job_no=job_no)
                        bars_for_job = bars_by_job_no.get(job_no, 0)

                        if item_unit == 'metre':
                            quantity = Decimal(str(bars_for_job * (stock_len / 1000)))
                        else:
                            quantity = Decimal(bars_for_job)

                        item_description = f"{bars_for_job} boy {stock_len_m} metre"
                        specs = ", ".join(
                            f"{p.label} {p.nominal_length_mm}mm ×{p.quantity}"
                            for p in parts_for_job
                        )

                        PlanningRequestItem.objects.create(
                            planning_request=pr,
                            item=item_obj,
                            job_no=job_no,
                            quantity=quantity,
                            quantity_to_purchase=quantity,
                            item_description=item_description,
                            specifications=specs,
                            order=order_idx,
                        )
                        order_idx += 1

                session.planning_request = pr
                session.planning_request_created = True

            session.save(update_fields=[
                'tasks_created', 'planning_request_created', 'planning_request',
            ])

        return Response({
            'created_tasks': created_task_keys,
            'planning_request_number': planning_request_number,
            'planning_request_already_existed': pr_already,
        })


# ─────────────────────────────────────────────────────────────────────────────
# PDF endpoint
# ─────────────────────────────────────────────────────────────────────────────

class CuttingListPDFView(APIView):
    """
    GET /linear_cutting/sessions/{key}/pdf/

    Returns a printable A4 PDF cutting list for the session.
    Each item group is rendered as a separate section.
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
# Task PDF endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TaskPDFView(APIView):
    """
    GET /linear_cutting/tasks/{key}/pdf/

    Returns a single-bar work-order PDF for one cutting task.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, key):
        try:
            task = LinearCuttingTask.objects.select_related('session', 'session__created_by').get(key=key)
        except LinearCuttingTask.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)

        pdf_bytes = build_task_pdf(task)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{task.key}_work_order.pdf"'
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Parts ViewSet (manage parts independently of session creation)
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingPartViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = LinearCuttingPartSerializer

    def get_queryset(self):
        qs = LinearCuttingPart.objects.select_related('item').all()
        session_key = self.request.query_params.get('session')
        if session_key:
            qs = qs.filter(session__key=session_key)
        return qs

    def create(self, request, *args, **kwargs):
        # Support both single object and list
        if isinstance(request.data, list):
            serializer = self.get_serializer(data=request.data, many=True)
            serializer.is_valid(raise_exception=True)
            with transaction.atomic():
                self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return super().create(request, *args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Task ViewSet
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingTaskViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['created_at', 'completion_date', 'bar_index']

    def get_queryset(self):
        qs = LinearCuttingTask.objects.select_related(
            'session', 'machine_fk', 'item'
        ).prefetch_related('issue_key')
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
