import time
import logging
from collections import defaultdict
from decimal import Decimal
from django.db import models, transaction
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

from .models import LinearCuttingSession, LinearCuttingPart, LinearCuttingTask, LinearCuttingStockBar
from .serializers import (
    LinearCuttingSessionListSerializer,
    LinearCuttingSessionDetailSerializer,
    LinearCuttingPartSerializer,
    LinearCuttingTaskListSerializer,
    LinearCuttingTaskDetailSerializer,
    LinearCuttingTimerSerializer,
    LinearCuttingStockBarSerializer,
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


def _notify_stock_entry_complete(session, actor):
    try:
        from notifications.service import notify, render_notification
        from notifications.models import Notification
        ctx = {
            'session_key':   session.key,
            'session_title': session.title,
            'actor':         actor.get_full_name() or actor.username,
        }
        title, body, link = render_notification(Notification.LC_STOCK_ENTRY_COMPLETE, ctx)
        notify(
            user=session.created_by,
            notification_type=Notification.LC_STOCK_ENTRY_COMPLETE,
            title=title,
            body=body,
            link=link,
            source_type='linear_cutting_session',
            source_id=session.key,
        )
    except Exception:
        logger.exception('Failed to send LC stock entry complete notification for %s', session.key)


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

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        was_complete = instance.stock_entry_complete
        response = super().partial_update(request, *args, **kwargs)
        instance.refresh_from_db(fields=['stock_entry_complete'])
        if not was_complete and instance.stock_entry_complete and instance.created_by_id:
            _notify_stock_entry_complete(instance, actor=request.user)
        return response


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

        raw_kerf = request.data.get('kerf_mm', None)
        try:
            kerf_mm = float(raw_kerf) if raw_kerf not in (None, '') else float(session.kerf_mm)
        except (TypeError, ValueError):
            return Response({'error': 'Geçersiz testere payı (kerf) değeri.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if kerf_mm < 0:
            return Response({'error': 'Testere payı negatif olamaz.'},
                            status=status.HTTP_400_BAD_REQUEST)

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
        # The same physical stock bars serve every group of an item; track
        # what earlier groups consumed so a remnant is never handed out twice.
        remnants_consumed: dict[int, int] = defaultdict(int)

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
                    'allow_rotation': p.allow_rotation,
                    'requires_bending': p.requires_bending,
                    'image_no': p.image_no,
                }
                for p in group_parts
            ]

            # Collect stock bars declared by warehouse for this session/item
            stock_bars_qs = LinearCuttingStockBar.objects.filter(
                session=session,
                item_id=item_id,
            ).values('id', 'length_mm', 'quantity')
            stock_pieces = []
            for r in stock_bars_qs:
                remaining = r['quantity'] - remnants_consumed[r['id']]
                if remaining > 0:
                    stock_pieces.append(
                        {'id': r['id'], 'length_mm': r['length_mm'], 'quantity': remaining}
                    )
            stock_pieces = stock_pieces or None

            try:
                result = optimize(parts_data, stock_len, kerf_mm, stock_pieces=stock_pieces)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            # Assign global bar indices across all groups
            for bar in result['bars']:
                global_bar_index += 1
                bar['global_bar_index'] = global_bar_index
                if bar.get('is_remnant') and bar.get('stock_bar_id'):
                    remnants_consumed[bar['stock_bar_id']] += 1

            groups.append({
                'item_id': item_id,
                'item_name': item_obj.name,
                'item_code': item_obj.code,
                'stock_length_mm': stock_len,
                'kerf_mm': kerf_mm,
                'bars_needed': result['bars_needed'],
                'remnant_bars_used': result.get('remnant_bars_used', 0),
                'total_waste_mm': result['total_waste_mm'],
                'efficiency_pct': result['efficiency_pct'],
                'total_pass_count': result.get('total_pass_count', 0),
                'saw_setup_changes': result.get('saw_setup_changes', 0),
                'nest_pairs_formed': result.get('nest_pairs_formed', 0),
                'material_saved_by_nesting_mm': result.get('material_saved_by_nesting_mm', 0.0),
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

        pr = session.planning_request
        pr_status = getattr(pr, 'status', None) if pr else None

        # Block if PR is past pending_inventory (already being processed)
        if pr is not None and pr_status not in (None, 'cancelled', 'pending_inventory'):
            return Response(
                {'error': 'Planning request is already past pending_inventory and cannot be updated.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Re-confirm mode: PR exists and is still pending_inventory
        is_reconfirm = (pr is not None and pr_status == 'pending_inventory')

        with transaction.atomic():
            from planning.models import PlanningRequest, PlanningRequestItem
            from procurement.models import Item as ProcurementItem
            from .models import LinearCuttingStockBarUsage

            needed_date = request.data.get('needed_date') or str(timezone.localdate())
            priority = request.data.get('priority', 'normal')
            total_bars = sum(g['bars_needed'] for g in groups)
            now_ms = int(time.time() * 1000)

            if is_reconfirm:
                pr.items.all().delete()
            else:
                pr = PlanningRequest(
                    title=f"Profil/Boru Kesim – {session.key} {session.title}",
                    description=(
                        f"Toplam {total_bars} bar, {len(groups)} farklı profil. "
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

                group_parts = LinearCuttingPart.objects.filter(session=session, item_id=item_id)
                if stock_len == session.stock_length_mm:
                    group_parts = group_parts.filter(
                        Q(stock_length_mm=stock_len) | Q(stock_length_mm__isnull=True)
                    )
                else:
                    group_parts = group_parts.filter(stock_length_mm=stock_len)

                distinct_job_nos = list(
                    group_parts.order_by('job_no').values_list('job_no', flat=True).distinct()
                )

                new_bars_by_job: dict[str, int] = defaultdict(int)
                remnant_bars_by_job: dict[str, list] = defaultdict(list)
                for bar in group['bars']:
                    cut_mm_by_job: dict[str, float] = defaultdict(float)
                    for cut in bar['cuts']:
                        cut_mm_by_job[cut['job_no']] += cut['effective_mm']
                    dominant_job = max(cut_mm_by_job, key=lambda j: cut_mm_by_job[j])
                    if bar.get('is_remnant'):
                        remnant_bars_by_job[dominant_job].append(bar['stock_length_mm'])
                    else:
                        new_bars_by_job[dominant_job] += 1

                specs_cache = {
                    job_no: ", ".join(
                        f"{p.label} {p.nominal_length_mm}mm ×{p.quantity}"
                        for p in group_parts.filter(job_no=job_no)
                    )
                    for job_no in distinct_job_nos
                }

                for job_no in distinct_job_nos:
                    specs = specs_cache[job_no]

                    new_bar_count = new_bars_by_job.get(job_no, 0)
                    if new_bar_count > 0:
                        if item_unit == 'metre':
                            quantity = Decimal(str(new_bar_count * (stock_len / 1000)))
                        else:
                            quantity = Decimal(new_bar_count)
                        PlanningRequestItem.objects.create(
                            planning_request=pr,
                            item=item_obj,
                            job_no=job_no,
                            quantity=quantity,
                            quantity_to_purchase=quantity,
                            item_description=f"{new_bar_count} boy {stock_len_m} metre (yeni)",
                            specifications=specs,
                            order=order_idx,
                        )
                        order_idx += 1

                    remnant_lengths = remnant_bars_by_job.get(job_no, [])
                    if remnant_lengths:
                        total_remnant_mm = sum(remnant_lengths)
                        if item_unit == 'metre':
                            rem_quantity = Decimal(str(round(total_remnant_mm / 1000, 3)))
                        else:
                            rem_quantity = Decimal(len(remnant_lengths))
                        lengths_str = ", ".join(f"{l}mm" for l in sorted(remnant_lengths, reverse=True))
                        PlanningRequestItem.objects.create(
                            planning_request=pr,
                            item=item_obj,
                            job_no=job_no,
                            quantity=rem_quantity,
                            quantity_from_inventory=rem_quantity,
                            quantity_to_purchase=Decimal('0'),
                            item_description=f"{len(remnant_lengths)} parça stoktan ({lengths_str})",
                            specifications=specs,
                            order=order_idx,
                        )
                        order_idx += 1

            created_task_keys = []

            if is_reconfirm:
                # ── Tasks (only created once layout is final) ─────────────
                LinearCuttingTask.objects.filter(session=session).delete()
                for group in groups:
                    item_id = group['item_id']
                    item_name = group['item_name']
                    for bar in group['bars']:
                        bar_idx = bar.get('global_bar_index', bar['bar_index'])
                        task_key = f"{session.key}-B{bar_idx}"
                        LinearCuttingTask.objects.create(
                            key=task_key,
                            session=session,
                            item_id=item_id,
                            bar_index=bar_idx,
                            stock_length_mm=bar['stock_length_mm'],
                            material=item_name,
                            layout_json=bar['cuts'],
                            passes_json=bar.get('passes'),
                            is_remnant_bar=bool(bar.get('is_remnant')),
                            waste_mm=bar['waste_mm'],
                            name=f"{session.title} – {item_name} Bar {bar_idx}",
                            quantity=1,
                            created_by=request.user,
                            created_at=now_ms,
                        )
                        created_task_keys.append(task_key)
                session.tasks_created = True

                # ── Stock bar usage: tally consumed IDs, decrement quantities ─
                usage_tally: dict[int, int] = defaultdict(int)
                for group in groups:
                    for bar in group['bars']:
                        if bar.get('is_remnant') and bar.get('stock_bar_id'):
                            usage_tally[bar['stock_bar_id']] += 1

                # Reverse the previous confirm's consumption before clearing
                # its usage records — otherwise a re-confirm decrements the
                # same stock bars twice.
                prior_usages = LinearCuttingStockBarUsage.objects.filter(session=session)
                for usage in prior_usages:
                    LinearCuttingStockBar.objects.filter(pk=usage.stock_bar_id).update(
                        quantity=models.F('quantity') + usage.quantity_used
                    )
                prior_usages.delete()

                for stock_bar_id, qty_used in usage_tally.items():
                    LinearCuttingStockBarUsage.objects.create(
                        session=session,
                        stock_bar_id=stock_bar_id,
                        quantity_used=qty_used,
                    )
                    LinearCuttingStockBar.objects.filter(pk=stock_bar_id).update(
                        quantity=models.F('quantity') - qty_used
                    )

                pr.status = 'pending_erp_entry'
                pr.save(update_fields=['status'])
                session.save(update_fields=['tasks_created'])
            else:
                session.planning_request = pr
                session.planning_request_created = True
                session.save(update_fields=['planning_request_created', 'planning_request'])

        return Response({
            'created_tasks': created_task_keys,
            'planning_request_number': planning_request_number,
            'reconfirmed': is_reconfirm,
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


# ─────────────────────────────────────────────────────────────────────────────
# Stock bar registry (per-session, declared by warehouse)
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingStockBarViewSet(ModelViewSet):
    """
    GET    /linear_cutting/stock-bars/?session=LC-0007  — list for a session
    POST   /linear_cutting/stock-bars/                  — create one or bulk list
    PATCH  /linear_cutting/stock-bars/{id}/             — update entry
    DELETE /linear_cutting/stock-bars/{id}/             — delete freely
    Adding or deleting entries resets session.stock_entry_complete to False.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = LinearCuttingStockBarSerializer

    def get_queryset(self):
        qs = LinearCuttingStockBar.objects.select_related('item', 'session', 'declared_by').all()
        session_key = self.request.query_params.get('session')
        if session_key:
            qs = qs.filter(session__key=session_key)
        item_id = self.request.query_params.get('item')
        if item_id:
            qs = qs.filter(item_id=item_id)
        return qs

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            return self._bulk_sync(request)
        return super().create(request, *args, **kwargs)

    def _bulk_sync(self, request):
        """
        Replace the stock bars for a session with the provided list.
        Items with an 'id' field are updated in-place; items without 'id' are
        created; existing bars whose id is not present in the payload are deleted.
        All items in the list must belong to the same session.
        Session is resolved from the items' 'session' field or the ?session= query param.
        """
        items = request.data

        # Resolve session key from items or query param
        session_keys = {item.get('session') for item in items if item.get('session')}
        qp_session = request.query_params.get('session')
        if qp_session:
            session_keys.add(qp_session)

        if len(session_keys) != 1:
            return Response(
                {'error': 'Provide a single session key via the items or ?session= query param.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session_key = session_keys.pop()

        try:
            session = LinearCuttingSession.objects.get(pk=session_key)
        except LinearCuttingSession.DoesNotExist:
            return Response({'error': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)

        now_ms = int(time.time() * 1000)
        user = request.user

        with transaction.atomic():
            incoming_ids = {int(item['id']) for item in items if item.get('id')}
            # Delete bars not in the incoming list
            LinearCuttingStockBar.objects.filter(session=session).exclude(
                pk__in=incoming_ids
            ).delete()

            result = []
            for item in items:
                bar_id = item.get('id')
                if bar_id:
                    # Update existing
                    try:
                        bar = LinearCuttingStockBar.objects.get(pk=bar_id, session=session)
                    except LinearCuttingStockBar.DoesNotExist:
                        # Undo this atomic block's deletions before erroring —
                        # returning (not raising) would otherwise commit them.
                        transaction.set_rollback(True)
                        return Response(
                            {'error': f'Stock bar id={bar_id} not found in session {session_key}.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    serializer = self.get_serializer(bar, data=item, partial=True)
                    serializer.is_valid(raise_exception=True)
                    bar = serializer.save()
                else:
                    # Create new
                    serializer = self.get_serializer(data=item)
                    serializer.is_valid(raise_exception=True)
                    bar = serializer.save(
                        declared_by=user,
                        declared_at=now_ms,
                    )
                result.append(bar)

            LinearCuttingSession.objects.filter(pk=session.pk).update(stock_entry_complete=False)

        return Response(
            LinearCuttingStockBarSerializer(result, many=True).data,
            status=status.HTTP_200_OK,
        )

    def perform_create(self, serializer):
        now_ms = int(time.time() * 1000)
        instances = serializer.save(
            declared_by=self.request.user,
            declared_at=now_ms,
        )
        if isinstance(instances, list) and instances:
            session = instances[0].session
        elif hasattr(instances, 'session'):
            session = instances.session
        else:
            return
        LinearCuttingSession.objects.filter(pk=session.pk).update(stock_entry_complete=False)

    def perform_destroy(self, instance):
        session_pk = instance.session_id
        instance.delete()
        LinearCuttingSession.objects.filter(pk=session_pk).update(stock_entry_complete=False)
