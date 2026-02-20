from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import QCReview, NCR
from .serializers import (
    QCReviewListSerializer, QCReviewDetailSerializer,
    QCReviewSubmitSerializer, QCReviewBulkSubmitSerializer, QCDecisionSerializer,
    NCRListSerializer, NCRDetailSerializer,
    NCRCreateSerializer, NCRUpdateSerializer, NCRSubmitSerializer, NCRDecisionSerializer,
)
from .approval_service import (
    submit_for_qc_review, bulk_submit_for_qc_review, decide_qc_review,
    submit_ncr, decide_ncr,
    email_ncr_assigned_members,
)


def _is_qc_member(user):
    return (
        user.is_superuser
        or getattr(getattr(user, 'profile', None), 'team', None) == 'qualitycontrol'
    )


# =============================================================================
# QCReview
# =============================================================================

class QCReviewViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for QC reviews (list + retrieve).
    Submission and decisions are handled via custom actions.

    POST /qc-reviews/submit/        — submit a task for QC review
    POST /qc-reviews/{id}/decide/   — QC team approve/reject
    """
    queryset = QCReview.objects.select_related(
        'task', 'task__job_order', 'submitted_by', 'reviewed_by', 'ncr'
    ).order_by('-submitted_at')
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'task': ['exact'],
        'status': ['exact', 'in'],
        'task__job_order': ['exact'],
        'task__department': ['exact'],
    }
    search_fields = ['task__title', 'task__job_order__job_no']
    ordering_fields = ['submitted_at', 'status']

    def get_serializer_class(self):
        if self.action == 'list':
            return QCReviewListSerializer
        return QCReviewDetailSerializer

    @action(detail=False, methods=['post'])
    def submit(self, request):
        """Submit a task to QC for review. Body: {task_id: <id>}"""
        serializer = QCReviewSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.validated_data['task_id']  # already a task instance from validate_task_id
        part_data = serializer.validated_data.get('part_data') or {}
        try:
            review = submit_for_qc_review(task, submitted_by=request.user, part_data=part_data)
            return Response(
                QCReviewDetailSerializer(review).data,
                status=status.HTTP_201_CREATED
            )
        except ValueError as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='bulk_submit')
    def bulk_submit(self, request):
        """
        Submit multiple QC reviews for a single task at once.
        Each entry in `reviews` becomes one QCReview with its own part_data.

        Body: { "task_id": <id>, "reviews": [ {}, {"location": "A1"}, ... ] }
        """
        serializer = QCReviewBulkSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.validated_data['task_id']  # already a task instance
        part_data_list = serializer.validated_data['reviews']
        try:
            reviews = bulk_submit_for_qc_review(task, submitted_by=request.user, part_data_list=part_data_list)
            return Response(
                QCReviewDetailSerializer(reviews, many=True).data,
                status=status.HTTP_201_CREATED,
            )
        except ValueError as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def decide(self, request, pk=None):
        """QC team member approves or rejects a review. Body: {approve: bool, comment: str}"""
        if not _is_qc_member(request.user):
            return Response(
                {'status': 'error', 'message': 'Sadece Kalite Kontrol ekibi karar verebilir.'},
                status=status.HTTP_403_FORBIDDEN
            )
        review = self.get_object()
        if review.status != 'pending':
            return Response(
                {'status': 'error', 'message': 'Bu inceleme zaten sonuçlandırılmış.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = QCDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        ncr_data = {
            'title': vd.get('ncr_title', ''),
            'description': vd.get('ncr_description', ''),
            'defect_type': vd.get('ncr_defect_type', 'other'),
            'severity': vd.get('ncr_severity', 'minor'),
            'affected_quantity': vd.get('ncr_affected_quantity', 1),
            'disposition': vd.get('ncr_disposition', 'pending'),
        }
        try:
            decide_qc_review(
                review,
                user=request.user,
                approve=vd['approve'],
                comment=vd.get('comment', ''),
                ncr_data=ncr_data if not vd['approve'] else None,
            )
            review.refresh_from_db()
            return Response(QCReviewDetailSerializer(review).data)
        except ValueError as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# =============================================================================
# NCR
# =============================================================================

class NCRViewSet(viewsets.ModelViewSet):
    """
    NCR (Non-Conformance Report) CRUD + workflow actions.

    POST /ncrs/                 — create manual NCR (notifies assigned_members)
    GET  /ncrs/                 — list NCRs
    GET  /ncrs/{id}/            — NCR detail
    PATCH /ncrs/{id}/           — update NCR fields
    POST /ncrs/{id}/submit/     — submit for QC approval (draft → submitted)
    POST /ncrs/{id}/decide/     — QC team approve/reject
    POST /ncrs/{id}/close/      — close an approved NCR
    """
    queryset = NCR.objects.select_related(
        'job_order', 'department_task', 'qc_review',
        'created_by', 'detected_by'
    ).prefetch_related('assigned_members').order_by('-created_at')
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        'job_order': ['exact'],
        'status': ['exact', 'in'],
        'severity': ['exact', 'in'],
        'defect_type': ['exact'],
        'assigned_team': ['exact'],
        'department_task': ['exact'],
    }
    search_fields = ['ncr_number', 'title', 'description', 'job_order__job_no']
    ordering_fields = ['created_at', 'severity', 'status']

    def get_serializer_class(self):
        if self.action == 'list':
            return NCRListSerializer
        if self.action == 'create':
            return NCRCreateSerializer
        if self.action in ('update', 'partial_update'):
            return NCRUpdateSerializer
        if self.action == 'submit':
            return NCRSubmitSerializer
        if self.action == 'decide':
            return NCRDecisionSerializer
        return NCRDetailSerializer

    def perform_create(self, serializer):
        return serializer.save(created_by=self.request.user, status='draft')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ncr = self.perform_create(serializer)
        # Notify assigned members after M2M is saved
        if ncr.assigned_members.exists():
            email_ncr_assigned_members(ncr)
        return Response(NCRDetailSerializer(ncr).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit NCR for QC approval. Optionally update fields (root_cause, corrective_action, etc.) in the same request."""
        ncr = self.get_object()
        serializer = NCRSubmitSerializer(ncr, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            submit_ncr(ncr, by_user=request.user, field_updates=serializer.validated_data)
            ncr.refresh_from_db()
            return Response(NCRDetailSerializer(ncr).data)
        except ValueError as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def decide(self, request, pk=None):
        """QC team approve/reject an NCR."""
        if not _is_qc_member(request.user):
            return Response(
                {'status': 'error', 'message': 'Sadece Kalite Kontrol ekibi karar verebilir.'},
                status=status.HTTP_403_FORBIDDEN
            )
        ncr = self.get_object()
        if ncr.status != 'submitted':
            return Response(
                {'status': 'error', 'message': 'Sadece gönderilmiş NCR\'lar onaylanabilir/reddedilebilir.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = NCRDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            decide_ncr(
                ncr,
                user=request.user,
                approve=serializer.validated_data['approve'],
                comment=serializer.validated_data.get('comment', ''),
            )
            ncr.refresh_from_db()
            return Response(NCRDetailSerializer(ncr).data)
        except ValueError as e:
            return Response({'status': 'error', 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close an approved NCR and unblock the linked task if still blocked."""
        ncr = self.get_object()
        if ncr.status != 'approved':
            return Response(
                {'status': 'error', 'message': "Sadece onaylanmış NCR'lar kapatılabilir."},
                status=status.HTTP_400_BAD_REQUEST
            )
        from django.db import transaction
        with transaction.atomic():
            ncr.status = 'closed'
            ncr.save(update_fields=['status'])
            task = ncr.department_task
            if task and task.status == 'blocked':
                task.status = 'in_progress'
                task.save(update_fields=['status'])
        return Response(NCRDetailSerializer(ncr).data)
