from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from django.db.models import Q, F, OuterRef, Exists, Subquery
from django.db.models.query import Prefetch
from django.contrib.contenttypes.models import ContentType
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import DepartmentRequest, PlanningRequest, PlanningRequestItem, FileAttachment, FileAsset
from procurement.models import Item
from .serializers import (
    DepartmentRequestSerializer,
    PlanningRequestSerializer,
    PlanningRequestCreateSerializer,
    PlanningRequestItemSerializer,
    BulkPlanningRequestItemSerializer,
    AttachmentUploadSerializer,
    FileAttachmentSerializer,
)
from procurement.permissions import IsFinanceAuthorized
from approvals.models import ApprovalWorkflow, ApprovalStageInstance, ApprovalDecision


def _create_attachment_for_target(target, attachment_data, user):
    """Helper to build FileAsset + FileAttachment for a target object."""
    source_attachment = None
    source_id = attachment_data.get('source_attachment_id')
    if source_id:
        try:
            source_attachment = FileAttachment.objects.get(id=source_id)
        except FileAttachment.DoesNotExist:
            raise ValidationError({"attachments": f"source_attachment_id {source_id} not found"})

    asset = FileAsset.objects.create(
        file=attachment_data['file'],
        uploaded_by=user,
        description=attachment_data.get('description', '')
    )
    ct = ContentType.objects.get_for_model(target)
    return FileAttachment.objects.create(
        asset=asset,
        uploaded_by=user,
        description=attachment_data.get('description', ''),
        source_attachment=source_attachment,
        content_type=ct,
        object_id=target.id,
    )


class DepartmentRequestViewSet(viewsets.ModelViewSet):
    """
    Simple ViewSet for department requests.
    Flow: Department user creates -> Department head approves -> Planning marks as transferred
    """
    queryset = DepartmentRequest.objects.all()
    serializer_class = DepartmentRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_fields = ['status', 'department', 'priority', 'requestor']
    ordering_fields = ['id', 'created_at', 'needed_date', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        qs = DepartmentRequest.objects.select_related('requestor', 'approved_by').prefetch_related(
            Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
        )

        # Prefetch approval workflows
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

        # Filter based on user role
        # Superusers and planning team see all
        if user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning'):
            return qs

        # Regular users see only their own requests
        return qs.filter(requestor=user)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def approve(self, request, pk=None):
        """Approve department request (department head)"""
        from planning.services import decide_department_request

        dr = self.get_object()

        if dr.status != 'submitted':
            return Response({"detail": "Only submitted requests can be approved."}, status=400)

        try:
            decide_department_request(dr, request.user, approve=True, comment=request.data.get("comment", ""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response({"detail": "Request approved."})

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def reject(self, request, pk=None):
        """Reject department request (department head)"""
        from planning.services import decide_department_request

        dr = self.get_object()

        if dr.status != 'submitted':
            return Response({"detail": "Only submitted requests can be rejected."}, status=400)

        try:
            decide_department_request(dr, request.user, approve=False, comment=request.data.get("comment", ""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

        return Response({"detail": "Request rejected."})

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        """Upload and attach a file to this department request."""
        dr = self.get_object()
        upload_serializer = AttachmentUploadSerializer(data=request.data)
        if not upload_serializer.is_valid():
            return Response(upload_serializer.errors, status=400)

        attachment = _create_attachment_for_target(dr, upload_serializer.validated_data, request.user)
        return Response(FileAttachmentSerializer(attachment, context={'request': request}).data, status=201)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def my_requests(self, request):
        """Get current user's department requests"""
        user = request.user
        queryset = self.get_queryset().filter(requestor=user)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def pending_approval(self, request):
        """Get department requests pending approval by current user"""
        user = request.user
        ct_dr = ContentType.objects.get_for_model(DepartmentRequest)

        # Get open CURRENT stages where I am an approver and haven't decided
        my_decision_qs = ApprovalDecision.objects.filter(stage_instance=OuterRef('pk'), approver=user)

        stages_qs = (
            ApprovalStageInstance.objects
            .filter(
                workflow__content_type=ct_dr,
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

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def approved_requests(self, request):
        """Get approved department requests waiting to be processed by planning"""
        user = request.user

        # Only planning team and superusers can see this
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can access this endpoint."}, status=403)

        queryset = self.get_queryset().filter(status='approved').order_by('-approved_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def completed_requests(self, request):
        """Get transferred department requests (processed by planning)"""
        user = request.user

        # Only planning team and superusers can see this
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can access this endpoint."}, status=403)

        queryset = self.get_queryset().filter(status='transferred').order_by('-approved_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['PATCH'], permission_classes=[permissions.IsAuthenticated])
    def mark_transferred(self, request, pk=None):
        """
        Mark approved department request as transferred (planning team only).
        Simply changes status to 'transferred'.
        """
        dr = self.get_object()
        user = request.user

        # Only planning team and superusers can mark as transferred
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can mark requests as transferred."}, status=403)

        if dr.status != 'approved':
            return Response({"detail": "Only approved requests can be marked as transferred."}, status=400)

        # Simply change status
        dr.status = 'transferred'
        dr.save(update_fields=['status'])

        return Response({"detail": "Department request marked as transferred."})


class PlanningRequestViewSet(viewsets.ModelViewSet):
    """
    Planning team manages requests by mapping department requests to catalog items.
    Flow:
    1. Planning creates from approved DepartmentRequest
    2. Planning maps items (creates/selects catalog Items)
    3. Planning marks as 'ready'
    4. Procurement converts to PurchaseRequest
    """
    queryset = PlanningRequest.objects.all()
    serializer_class = PlanningRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['status', 'priority', 'created_by', 'department_request']
    ordering_fields = ['id', 'created_at', 'needed_date', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        qs = PlanningRequest.objects.select_related(
            'created_by', 'department_request', 'purchase_request'
        ).prefetch_related(
            'items__item',
            Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
            Prefetch('department_request__files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
            Prefetch('items__files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
        )

        # Planning team and superusers see all
        if user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning'):
            return qs

        # Procurement team sees only 'ready' requests
        if hasattr(user, 'profile') and user.profile.team == 'procurement':
            return qs.filter(status='ready')

        # Others see nothing
        return qs.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return PlanningRequestCreateSerializer
        return PlanningRequestSerializer

    def perform_create(self, serializer):
        # Handled by the serializer's create method
        serializer.save()

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def ready_for_procurement(self, request):
        """Get planning requests ready for procurement to convert."""
        user = request.user

        # Only procurement team can access
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'procurement')):
            return Response({"detail": "Only procurement team can access this endpoint."}, status=403)

        queryset = self.get_queryset().filter(status='ready').order_by('-ready_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def mark_ready(self, request, pk=None):
        """Planning marks request as ready for procurement."""
        from planning.services import mark_planning_request_ready

        planning_request = self.get_object()
        user = request.user

        # Only planning team can mark ready
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can mark requests as ready."}, status=403)

        try:
            mark_planning_request_ready(planning_request)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

        serializer = self.get_serializer(planning_request)
        return Response(serializer.data)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        """Upload and attach a file to this planning request."""
        planning_request = self.get_object()
        upload_serializer = AttachmentUploadSerializer(data=request.data)
        if not upload_serializer.is_valid():
            return Response(upload_serializer.errors, status=400)

        attachment = _create_attachment_for_target(planning_request, upload_serializer.validated_data, request.user)
        return Response(FileAttachmentSerializer(attachment, context={'request': request}).data, status=201)

    @action(detail=True, methods=['POST'], permission_classes=[IsFinanceAuthorized])
    def convert_to_purchase_request(self, request, pk=None):
        """Procurement converts planning request to purchase request."""
        from planning.services import convert_planning_request_to_purchase_request

        planning_request = self.get_object()
        user = request.user

        try:
            pr = convert_planning_request_to_purchase_request(planning_request, user)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "detail": "Successfully converted to purchase request.",
            "purchase_request_id": pr.id,
            "request_number": pr.request_number
        }, status=201)

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def my_requests(self, request):
        """Get current user's planning requests."""
        user = request.user
        queryset = self.get_queryset().filter(created_by=user)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class PlanningRequestItemViewSet(viewsets.ModelViewSet):
    """
    Manage individual items within a planning request.
    Planning team uses this to map department request items to catalog items.
    """
    queryset = PlanningRequestItem.objects.all()
    serializer_class = PlanningRequestItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['planning_request', 'item', 'job_no']
    ordering_fields = ['order', 'id']
    ordering = ['order']

    def get_queryset(self):
        user = self.request.user
        qs = PlanningRequestItem.objects.select_related('planning_request', 'item').prefetch_related(
            Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment'))
        )

        # Filter by planning_request param if provided
        pr_id = self.request.query_params.get('planning_request')
        if pr_id:
            qs = qs.filter(planning_request_id=pr_id)

        # Only planning team can manage items
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return qs.none()

        return qs

    def perform_create(self, serializer):
        # Extract item_id if provided
        item_id = serializer.validated_data.pop('item_id', None)
        attachments_data = serializer.validated_data.pop('attachments', [])
        user = self.request.user
        if item_id:
            try:
                item = Item.objects.get(id=item_id)
                instance = serializer.save(item=item)
            except Item.DoesNotExist:
                raise ValidationError({"item_id": "Item not found."})
        else:
            instance = serializer.save()

        for att in attachments_data:
            _create_attachment_for_target(instance, att, user)

    @action(detail=False, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def bulk_create(self, request):
        """
        Bulk create multiple planning request items at once.

        Request body:
        {
          "planning_request_id": 1,
          "items": [
            {
              "item_code": "PIPE-2IN-STEEL",  // OR "item_id": 123
              "job_no": "JOB-2024-001",
              "quantity": "50.00",
              "priority": "normal",           // optional
              "specifications": "2 inch"      // optional
            },
            {
              "item_id": 456,
              "job_no": "JOB-2024-002",
              "quantity": "30.00"
            }
          ]
        }
        """
        user = request.user

        # Only planning team can bulk import
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can bulk import items."}, status=403)

        serializer = BulkPlanningRequestItemSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        result = serializer.save()

        return Response({
            "detail": f"Successfully created {result['count']} items.",
            "planning_request_id": result['planning_request'].id,
            "created_count": result['count'],
            "items": PlanningRequestItemSerializer(result['created_items'], many=True).data
        }, status=201)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        """Upload and attach a file to this planning request item."""
        item = self.get_object()
        upload_serializer = AttachmentUploadSerializer(data=request.data)
        if not upload_serializer.is_valid():
            return Response(upload_serializer.errors, status=400)

        attachment = _create_attachment_for_target(item, upload_serializer.validated_data, request.user)
        return Response(FileAttachmentSerializer(attachment, context={'request': request}).data, status=201)


class FileAttachmentViewSet(viewsets.GenericViewSet):
    """
    ViewSet for managing file attachments.
    Only supports delete - files are created via parent object endpoints.
    """
    queryset = FileAttachment.objects.all()
    serializer_class = FileAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def destroy(self, request, pk=None):
        """
        Delete a file attachment.
        Also deletes the underlying FileAsset if no other attachments reference it.
        """
        try:
            attachment = FileAttachment.objects.select_related('asset').get(pk=pk)
        except FileAttachment.DoesNotExist:
            return Response({"detail": "File attachment not found."}, status=404)

        asset = attachment.asset

        # Delete the attachment
        attachment.delete()

        # Check if asset has any remaining attachments
        if asset and not asset.attachments.exists():
            # Delete the actual file from storage
            if asset.file:
                asset.file.delete(save=False)
            # Delete the asset record
            asset.delete()

        return Response(status=204)


class ItemSuggestionView(APIView):
    """
    Suggest catalog items based on a text description.
    Uses simple keyword matching for now.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        """
        POST /api/planning/item-suggestions/
        Body: { "description": "steel pipe 2 inch 100 metres" }

        Returns: List of suggested items with match scores
        """
        description = request.data.get('description', '').strip()
        if not description:
            return Response({"detail": "Description is required."}, status=400)

        # Simple keyword matching
        words = description.lower().split()

        # Filter items that contain any of the keywords
        q_objects = Q()
        for word in words:
            if len(word) >= 3:  # Skip very short words
                q_objects |= Q(name__icontains=word) | Q(code__icontains=word)

        if not q_objects:
            return Response({"suggestions": []})

        items = Item.objects.filter(q_objects).distinct()[:10]

        # Calculate simple match scores (count of matching words)
        suggestions = []
        for item in items:
            item_text = f"{item.code} {item.name}".lower()
            matches = sum(1 for word in words if len(word) >= 3 and word in item_text)
            score = int((matches / len([w for w in words if len(w) >= 3])) * 100) if words else 0

            suggestions.append({
                'item_id': item.id,
                'code': item.code,
                'name': item.name,
                'unit': item.unit,
                'match_score': score,
            })

        # Sort by score descending
        suggestions.sort(key=lambda x: x['match_score'], reverse=True)

        return Response({
            'description': description,
            'suggestions': suggestions[:5]  # Top 5
        })
