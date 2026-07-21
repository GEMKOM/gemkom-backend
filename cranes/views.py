from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, F, OuterRef, Subquery
from django.db.models.query import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.response import Response

from approvals.models import ApprovalDecision, ApprovalStageInstance, ApprovalWorkflow
from planning.models import FileAttachment
from planning.serializers import AttachmentUploadSerializer, FileAttachmentSerializer
from planning.views import _create_attachment_for_target
from users.permissions import user_has_role_perm

from .models import CraneRate, CraneRequest, CraneType
from .serializers import (
    CraneRateSerializer,
    CraneRequestListSerializer,
    CraneRequestSerializer,
    CraneTypeSerializer,
)
from .services import FACTORY_JOB_NO


class CanManageCranePricesOrReadOnly(permissions.BasePermission):
    """Reads for any authenticated user; writes require manage_crane_prices."""

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return u.is_superuser or u.is_staff or user_has_role_perm(u, 'manage_crane_prices')


class CraneTypeViewSet(viewsets.ModelViewSet):
    """Crane/platform catalog with current rates."""
    serializer_class = CraneTypeSerializer
    permission_classes = [CanManageCranePricesOrReadOnly]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['category', 'is_active']
    ordering = ['sort_order', 'id']

    def get_queryset(self):
        qs = CraneType.objects.prefetch_related(
            Prefetch('rates', queryset=CraneRate.objects.order_by('-effective_from'))
        )
        include_inactive = self.request.query_params.get('include_inactive')
        if include_inactive not in ('true', '1'):
            qs = qs.filter(is_active=True)
        return qs


class CraneRateViewSet(viewsets.ModelViewSet):
    """
    Price history per crane type. Price changes create NEW rows
    (effective-dated); past rows are never updated or deleted.
    """
    serializer_class = CraneRateSerializer
    permission_classes = [CanManageCranePricesOrReadOnly]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['crane_type']
    ordering = ['-effective_from']
    http_method_names = ['get', 'post', 'head', 'options']  # no update/delete — history is immutable

    def get_queryset(self):
        return CraneRate.objects.select_related('crane_type', 'created_by')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class CraneRequestViewSet(viewsets.ModelViewSet):
    """
    Crane/platform rental requests.
    Flow: department user creates (auto-submit) -> department manager approves
    -> coordination team arranges the rental and records actuals (complete).
    """
    queryset = CraneRequest.objects.all()
    serializer_class = CraneRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ['status', 'department', 'priority', 'requestor', 'crane_type', 'job_no']
    ordering_fields = ['id', 'created_at', 'needed_date', 'priority']
    ordering = ['-created_at']
    http_method_names = ['get', 'post', 'head', 'options']  # edits happen via actions only

    def get_queryset(self):
        if self.action in ['list', 'my_requests', 'pending_approval']:
            qs = CraneRequest.objects.select_related(
                'requestor', 'approved_by', 'completed_by', 'crane_type'
            )
        else:
            qs = CraneRequest.objects.select_related(
                'requestor', 'approved_by', 'completed_by', 'crane_type'
            ).prefetch_related(
                Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
            )
            wf_qs = (
                ApprovalWorkflow.objects
                .select_related("policy")
                .prefetch_related(
                    "stage_instances",
                    "stage_instances__decisions__approver",
                )
                .order_by("-created_at")
            )
            qs = qs.prefetch_related(Prefetch("approvals", queryset=wf_qs))
        return qs

    def get_serializer_class(self):
        if self.action in ['list', 'my_requests', 'pending_approval']:
            return CraneRequestListSerializer
        return CraneRequestSerializer

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def approve(self, request, pk=None):
        """Approve crane request (department manager)."""
        from .services import decide_crane_request

        cr = self.get_object()
        if cr.status != 'submitted':
            return Response({"detail": "Sadece onay bekleyen talepler onaylanabilir."}, status=400)

        try:
            decide_crane_request(cr, request.user, approve=True, comment=request.data.get("comment", ""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response({"detail": "Talep onaylandı."})

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def reject(self, request, pk=None):
        """Reject crane request (department manager)."""
        from .services import decide_crane_request

        cr = self.get_object()
        if cr.status != 'submitted':
            return Response({"detail": "Sadece onay bekleyen talepler reddedilebilir."}, status=400)

        try:
            decide_crane_request(cr, request.user, approve=False, comment=request.data.get("comment", ""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response({"detail": "Talep reddedildi."})

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):
        """Requestor cancels their own submitted request."""
        from .services import cancel_crane_request

        cr = self.get_object()
        try:
            cancel_crane_request(cr, request.user)
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response({"detail": "Talep iptal edildi."})

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def complete(self, request, pk=None):
        """
        Coordination team records actual quantity + cost; the actual cost
        flows into the job cost summary. Callable again on a completed
        request to correct the actuals — the job cost is re-summed.
        """
        from .services import complete_crane_request

        cr = self.get_object()

        actual_quantity = request.data.get('actual_quantity')
        actual_cost = request.data.get('actual_cost')
        currency = request.data.get('actual_cost_currency') or 'TRY'
        if actual_cost in (None, ''):
            return Response({"detail": "Fiili maliyet (actual_cost) zorunludur."}, status=400)

        try:
            complete_crane_request(
                cr, request.user,
                actual_quantity=actual_quantity or None,
                actual_cost=actual_cost,
                currency=currency,
            )
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        # Outside the service transaction (already committed): push the cost
        # into the job cost summary. Synthetic factory job has no JobOrder row.
        if cr.job_no != FACTORY_JOB_NO:
            from projects.services.costing import recompute_job_cost_summary
            recompute_job_cost_summary(cr.job_no)

        return Response(CraneRequestSerializer(cr, context={'request': request}).data)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        """Upload and attach a file to this crane request."""
        cr = self.get_object()
        upload_serializer = AttachmentUploadSerializer(data=request.data)
        if not upload_serializer.is_valid():
            return Response(upload_serializer.errors, status=400)

        attachment = _create_attachment_for_target(cr, upload_serializer.validated_data, request.user)
        return Response(FileAttachmentSerializer(attachment, context={'request': request}).data, status=201)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def my_permissions(self, request):
        """User-level flags for the crane requests UI (avoids per-row checks)."""
        from .services import user_can_complete

        u = request.user
        return Response({
            'can_complete': user_can_complete(u),
            'can_manage_prices': bool(
                u.is_superuser or u.is_staff or user_has_role_perm(u, 'manage_crane_prices')
            ),
        })

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def my_requests(self, request):
        """Current user's crane requests."""
        queryset = self.filter_queryset(self.get_queryset().filter(requestor=request.user))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def pending_approval(self, request):
        """Crane requests pending approval by the current user."""
        user = request.user
        ct_cr = ContentType.objects.get_for_model(CraneRequest)

        my_decision_qs = ApprovalDecision.objects.filter(stage_instance=OuterRef('pk'), approver=user)

        stages_qs = (
            ApprovalStageInstance.objects
            .filter(
                workflow__content_type=ct_cr,
                order=F('workflow__current_stage_order'),
                is_complete=False,
                is_rejected=False,
                approver_user_ids__contains=[user.id],
            )
            .annotate(already_decided=Exists(my_decision_qs))
            .filter(already_decided=False)
            .values_list('workflow__object_id', flat=True)
        )

        queryset = (
            self.get_queryset()
            .filter(id__in=Subquery(stages_qs), status='submitted')
            .exclude(requestor=user)
            .order_by('-created_at')
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
