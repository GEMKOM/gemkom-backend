from __future__ import annotations

from django.db import models
from django.db import transaction as db_transaction
from rest_framework import serializers as drf_serializers
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .approval_service import decide_statement, submit_statement
from .models import (
    Subcontractor,
    SubcontractingAssignment,
    SubcontractingPriceTier,
    SubcontractorStatement,
    SubcontractorStatementAdjustment,
)
from .serializers import (
    SubcontractingAssignmentSerializer,
    SubcontractingPriceTierSerializer,
    SubcontractorSerializer,
    SubcontractorStatementAdjustmentSerializer,
    SubcontractorStatementListSerializer,
    SubcontractorStatementSerializer,
)
from .services.statements import generate_or_refresh_statement


# ---------------------------------------------------------------------------
# Subcontractor CRUD
# ---------------------------------------------------------------------------

class SubcontractorViewSet(viewsets.ModelViewSet):
    queryset = Subcontractor.objects.all()
    serializer_class = SubcontractorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('true', '1', 'yes'))
        return qs


# ---------------------------------------------------------------------------
# SubcontractingPriceTier CRUD
# ---------------------------------------------------------------------------

class SubcontractingPriceTierViewSet(viewsets.ModelViewSet):
    serializer_class = SubcontractingPriceTierSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SubcontractingPriceTier.objects.select_related('job_order')
        job_order = self.request.query_params.get('job_order')
        if job_order:
            qs = qs.filter(job_order=job_order)
        return qs

    @action(detail=True, methods=['get'], url_path='remaining-weight')
    def remaining_weight(self, request, pk=None):
        tier = self.get_object()
        return Response({
            'allocated_weight_kg': str(tier.allocated_weight_kg),
            'used_weight_kg': str(tier.used_weight_kg),
            'remaining_weight_kg': str(tier.remaining_weight_kg),
        })


# ---------------------------------------------------------------------------
# SubcontractingAssignment CRUD
# ---------------------------------------------------------------------------

class SubcontractingAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = SubcontractingAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = SubcontractingAssignment.objects.select_related(
            'department_task__job_order',
            'subcontractor',
            'price_tier',
        )
        subcontractor = self.request.query_params.get('subcontractor')
        job_no = self.request.query_params.get('job_no')
        if subcontractor:
            qs = qs.filter(subcontractor_id=subcontractor)
        if job_no:
            qs = qs.filter(department_task__job_order_id=job_no)
        return qs

    @action(detail=False, methods=['post'], url_path='create-with-subtask')
    def create_with_subtask(self, request):
        """
        Atomically create a subtask under a 'Kaynaklı İmalat' task and assign
        a subcontractor to it in one step.

        POST /subcontracting/assignments/create-with-subtask/
        Body:
          kaynak_task_id      – ID of the 'Kaynaklı İmalat' JobOrderDepartmentTask
          subcontractor       – Subcontractor ID
          price_tier          – SubcontractingPriceTier ID
          allocated_weight_kg – weight to assign (must fit in tier's remaining)
          title               – (optional) subtask title; defaults to subcontractor name
          weight              – (optional) subtask weight for progress calc, default 10
        """
        from projects.models import JobOrderDepartmentTask

        kaynak_task_id      = request.data.get('kaynak_task_id')
        subcontractor_id    = request.data.get('subcontractor')
        price_tier_id       = request.data.get('price_tier')
        allocated_weight_kg = request.data.get('allocated_weight_kg')
        subtask_weight      = int(request.data.get('weight', 10))
        subtask_title       = request.data.get('title', '').strip()

        missing = [k for k, v in {
            'kaynak_task_id': kaynak_task_id,
            'subcontractor': subcontractor_id,
            'price_tier': price_tier_id,
            'allocated_weight_kg': allocated_weight_kg,
        }.items() if not v]
        if missing:
            return Response(
                {'detail': f'Şu alanlar gereklidir: {", ".join(missing)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            kaynak_task = JobOrderDepartmentTask.objects.select_related('job_order').get(
                pk=kaynak_task_id
            )
        except JobOrderDepartmentTask.DoesNotExist:
            return Response(
                {'detail': 'Kaynaklı İmalat görevi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if kaynak_task.task_type != 'welding':
            return Response(
                {'detail': "Bu işlem yalnızca 'Kaynaklı İmalat' görevi üzerinde yapılabilir."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not subtask_title:
            try:
                subtask_title = Subcontractor.objects.get(pk=subcontractor_id).name
            except Subcontractor.DoesNotExist:
                return Response(
                    {'detail': 'Taşeron bulunamadı.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        subtask_weight = max(1, min(subtask_weight, 100))
        next_sequence = (
            kaynak_task.subtasks.aggregate(m=models.Max('sequence'))['m'] or 0
        ) + 1

        try:
            with db_transaction.atomic():
                subtask = JobOrderDepartmentTask.objects.create(
                    job_order=kaynak_task.job_order,
                    department=kaynak_task.department,
                    parent=kaynak_task,
                    title=subtask_title,
                    status='pending',
                    weight=subtask_weight,
                    sequence=next_sequence,
                    created_by=request.user,
                )

                serializer = SubcontractingAssignmentSerializer(
                    data={
                        'department_task': subtask.pk,
                        'subcontractor': subcontractor_id,
                        'price_tier': price_tier_id,
                        'allocated_weight_kg': allocated_weight_kg,
                    },
                    context={'request': request},
                )
                if not serializer.is_valid():
                    raise drf_serializers.ValidationError(serializer.errors)

                assignment = serializer.save(created_by=request.user)

        except drf_serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            SubcontractingAssignmentSerializer(assignment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# SubcontractorStatement CRUD + actions
# ---------------------------------------------------------------------------

class SubcontractorStatementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return SubcontractorStatementListSerializer
        return SubcontractorStatementSerializer

    def get_queryset(self):
        qs = SubcontractorStatement.objects.select_related('subcontractor')
        params = self.request.query_params
        if subcontractor := params.get('subcontractor'):
            qs = qs.filter(subcontractor_id=subcontractor)
        if year := params.get('year'):
            qs = qs.filter(year=year)
        if month := params.get('month'):
            qs = qs.filter(month=month)
        if status_param := params.get('status'):
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=False, methods=['post'], url_path='generate')
    def generate(self, request):
        """
        Create or refresh a monthly statement from current assignment progress.

        POST /subcontracting/statements/generate/
        Body: {subcontractor, year, month}
        """
        subcontractor_id = request.data.get('subcontractor')
        year = request.data.get('year')
        month = request.data.get('month')

        if not all([subcontractor_id, year, month]):
            return Response(
                {'detail': 'subcontractor, year ve month alanları gereklidir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            statement = generate_or_refresh_statement(
                subcontractor_id=int(subcontractor_id),
                year=int(year),
                month=int(month),
                created_by=request.user,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            SubcontractorStatementSerializer(statement, context={'request': request}).data,
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='generate-bulk')
    def generate_bulk(self, request):
        """
        Create or refresh statements for ALL active subcontractors for a given period.
        Skips subcontractors that have no assignments with unbilled progress.
        Already-submitted/approved statements for the period are left untouched.

        POST /subcontracting/statements/generate-bulk/
        Body: {year, month}

        Response: {
            created: [...],   # new statements
            refreshed: [...], # existing draft/rejected statements that were refreshed
            skipped: [...],   # subcontractors with no unbilled progress
            untouched: [...], # subcontractors with submitted/approved statements (not modified)
            errors: [...]     # any failures
        }
        """
        year = request.data.get('year')
        month = request.data.get('month')

        if not all([year, month]):
            return Response(
                {'detail': 'year ve month alanları gereklidir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            year = int(year)
            month = int(month)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'year ve month geçerli tam sayılar olmalıdır.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        active_subcontractors = Subcontractor.objects.filter(is_active=True)

        created, refreshed, skipped, untouched, errors = [], [], [], [], []

        for subcontractor in active_subcontractors:
            # Check if an immutable statement already exists for this period
            existing = SubcontractorStatement.objects.filter(
                subcontractor=subcontractor, year=year, month=month
            ).first()

            if existing and existing.status in ('submitted', 'approved', 'paid'):
                untouched.append({
                    'subcontractor_id': subcontractor.id,
                    'subcontractor_name': subcontractor.name,
                    'statement_id': existing.id,
                    'status': existing.status,
                })
                continue

            try:
                is_new = existing is None
                statement = generate_or_refresh_statement(
                    subcontractor_id=subcontractor.id,
                    year=year,
                    month=month,
                    created_by=request.user,
                )

                # Skip if the statement ended up with no line items (nothing to bill)
                if statement.work_total == 0 and not statement.adjustments.exists():
                    # Clean up empty draft we just created if it was brand new
                    if is_new:
                        statement.delete()
                    skipped.append({
                        'subcontractor_id': subcontractor.id,
                        'subcontractor_name': subcontractor.name,
                    })
                    continue

                entry = {
                    'subcontractor_id': subcontractor.id,
                    'subcontractor_name': subcontractor.name,
                    'statement_id': statement.id,
                    'work_total': str(statement.work_total),
                    'grand_total': str(statement.grand_total),
                    'currency': statement.currency,
                }
                (created if is_new else refreshed).append(entry)

            except Exception as e:
                errors.append({
                    'subcontractor_id': subcontractor.id,
                    'subcontractor_name': subcontractor.name,
                    'error': str(e),
                })

        return Response({
            'period': f'{year}/{month:02d}',
            'created': created,
            'refreshed': refreshed,
            'skipped': skipped,
            'untouched': untouched,
            'errors': errors,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='refresh')
    def refresh(self, request, pk=None):
        """Re-snapshot line items from current progress data (draft/rejected only)."""
        statement = self.get_object()
        try:
            statement = generate_or_refresh_statement(
                subcontractor_id=statement.subcontractor_id,
                year=statement.year,
                month=statement.month,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SubcontractorStatementSerializer(statement, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        """Submit a draft statement for approval."""
        statement = self.get_object()
        try:
            submit_statement(statement, by_user=request.user)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SubcontractorStatementSerializer(statement, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='decide')
    def decide(self, request, pk=None):
        """
        Approve or reject a submitted statement.

        Body: {approve: true/false, comment: "..."}
        """
        statement = self.get_object()
        approve = request.data.get('approve')
        comment = request.data.get('comment', '')

        if approve is None:
            return Response(
                {'detail': '"approve" alanı gereklidir (true/false).'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            decide_statement(statement, user=request.user, approve=bool(approve), comment=comment)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        statement.refresh_from_db()
        return Response(SubcontractorStatementSerializer(statement, context={'request': request}).data)


# ---------------------------------------------------------------------------
# SubcontractorStatementAdjustment
# ---------------------------------------------------------------------------

class SubcontractorStatementAdjustmentViewSet(viewsets.ModelViewSet):
    serializer_class = SubcontractorStatementAdjustmentSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        statement_pk = self.kwargs.get('statement_pk')
        return SubcontractorStatementAdjustment.objects.filter(statement_id=statement_pk)

    def _get_statement(self, pk):
        return SubcontractorStatement.objects.get(pk=pk)

    def perform_create(self, serializer):
        statement_pk = self.kwargs['statement_pk']
        statement = self._get_statement(statement_pk)

        if statement.status not in ('draft', 'rejected'):
            raise drf_serializers.ValidationError(
                'Yalnızca taslak veya reddedilmiş hakedişlere düzeltme eklenebilir.'
            )

        adj = serializer.save(
            statement=statement,
            created_by=self.request.user,
        )

        # Recalculate statement totals
        statement.recalculate_totals()
        statement.save(update_fields=['work_total', 'adjustment_total', 'grand_total'])

        return adj

    def perform_destroy(self, instance):
        statement = instance.statement
        if statement.status not in ('draft', 'rejected'):
            raise drf_serializers.ValidationError(
                'Yalnızca taslak veya reddedilmiş hakedişlerden düzeltme silinebilir.'
            )
        instance.delete()
        statement.recalculate_totals()
        statement.save(update_fields=['work_total', 'adjustment_total', 'grand_total'])
