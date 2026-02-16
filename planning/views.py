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

from .models import (
    DepartmentRequest, PlanningRequest, PlanningRequestItem,
    FileAttachment, FileAsset, InventoryAllocation
)
from procurement.models import Item
from .serializers import (
    DepartmentRequestSerializer,
    DepartmentRequestListSerializer,
    PlanningRequestSerializer,
    PlanningRequestListSerializer,
    PlanningRequestCreateSerializer,
    PlanningRequestUpdateSerializer,
    PlanningRequestItemSerializer,
    PlanningRequestItemListSerializer,
    BulkPlanningRequestItemSerializer,
    AttachmentUploadSerializer,
    FileAttachmentSerializer,
    InventoryAllocationSerializer,
    AllocateInventorySerializer,
    UpdateInventoryQuantitiesSerializer,
)
from .filters import PlanningRequestItemFilter, PlanningRequestFilter
from .permissions import CanMarkDelivered
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

        # For list views and list-like actions, use minimal prefetching
        if self.action in ['list', 'my_requests', 'pending_approval', 'approved_requests', 'completed_requests']:
            qs = DepartmentRequest.objects.select_related(
                'requestor', 'approved_by'
            ).prefetch_related('planning_requests')
        else:
            # For detail views, prefetch all related data
            qs = DepartmentRequest.objects.select_related('requestor', 'approved_by').prefetch_related(
                Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
            )

            # Prefetch approval workflows for detail views
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
        if user.is_superuser or (hasattr(user, 'profile') and (user.profile.team == 'planning' or user.profile.occupation == 'manager')):
            return qs

        # Regular users see only their own requests
        return qs.filter(requestor=user)

    def get_serializer_class(self):
        if self.action in ['list', 'my_requests', 'pending_approval', 'approved_requests', 'completed_requests']:
            return DepartmentRequestListSerializer
        return DepartmentRequestSerializer

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
    3. If check_inventory=true: conduct inventory control, then mark as ready/completed
    4. Procurement converts ready requests to PurchaseRequest
    """
    queryset = PlanningRequest.objects.all()
    serializer_class = PlanningRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filterset_class = PlanningRequestFilter
    ordering_fields = ['id', 'created_at', 'needed_date', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        from django.db.models import Count
        user = self.request.user

        # For list views and list-like actions, use minimal prefetching
        if self.action in ['list', 'ready_for_procurement', 'my_requests', 'warehouse_requests']:
            qs = PlanningRequest.objects.select_related(
                'created_by', 'department_request'
            ).annotate(
                items_count=Count('items')
            )
        else:
            # For detail views, prefetch all related data
            qs = PlanningRequest.objects.select_related(
                'created_by', 'department_request'
            ).prefetch_related(
                'items__item',
                'items__purchase_requests',
                Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
                Prefetch('items__files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment')),
            )

        # Planning team and superusers see all
        if user.is_superuser or (hasattr(user, 'profile') and (user.profile.team == 'planning' or user.profile.team == 'warehouse')):
            return qs

        # Procurement team sees only 'ready' requests
        if hasattr(user, 'profile') and user.profile.team == 'procurement':
            return qs.filter(status='ready')

        # Others see nothing
        return qs.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return PlanningRequestCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return PlanningRequestUpdateSerializer
        elif self.action in ['list', 'ready_for_procurement', 'my_requests', 'warehouse_requests']:
            return PlanningRequestListSerializer
        return PlanningRequestSerializer

    def create(self, request, *args, **kwargs):
        """Override create to use write serializer for input and read serializer for output."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        # Use the read serializer for the response
        read_serializer = PlanningRequestSerializer(instance, context={'request': request})
        headers = self.get_success_headers(read_serializer.data)
        return Response(read_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        """
        Update a planning request.
        Only planning team can update.
        Cannot update requests that are converted, completed, or cancelled.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        user = request.user

        # Only planning team can update
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response(
                {"detail": "Only planning team can update planning requests."},
                status=403
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Use the read serializer for the response
        read_serializer = PlanningRequestSerializer(instance, context={'request': request})
        return Response(read_serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update a planning request.
        Only planning team can update.
        Cannot update requests that are converted, completed, or cancelled.
        """
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

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

    @action(detail=True, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def check_inventory(self, request, pk=None):
        """
        Check inventory availability for all items in this planning request.
        Returns detailed availability information for each item.
        """
        from planning.services import check_inventory_availability

        planning_request = self.get_object()
        user = request.user

        # Only planning team can check inventory
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can check inventory."}, status=403)

        if not planning_request.check_inventory:
            return Response(
                {"detail": "This planning request doesn't have inventory control enabled."},
                status=400
            )

        availability_info = check_inventory_availability(planning_request)
        return Response(availability_info)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def auto_allocate_inventory(self, request, pk=None):
        """
        Automatically allocate available inventory to all items in this planning request.
        Only allocates what's available in stock.

        NOTE: This only allocates stock. You must call complete_inventory_control
        afterwards to mark the inventory control as done and update status.
        """
        from planning.services import auto_allocate_inventory

        planning_request = self.get_object()
        user = request.user

        # Only planning team can auto-allocate
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can allocate inventory."}, status=403)

        if not planning_request.check_inventory:
            return Response(
                {"detail": "This planning request doesn't have inventory control enabled."},
                status=400
            )

        if planning_request.status != 'pending_inventory':
            return Response(
                {"detail": f"Cannot allocate inventory. Planning request status is '{planning_request.status}'. Must be 'pending_inventory'."},
                status=400
            )

        try:
            result = auto_allocate_inventory(planning_request, user)
        except ValidationError as e:
            return Response({"detail": str(e)}, status=400)

        # Refresh planning request to get updated data
        planning_request.refresh_from_db()
        serializer = self.get_serializer(planning_request)

        return Response({
            "detail": "Inventory auto-allocation completed. Call complete_inventory_control to finalize.",
            "allocation_stats": result,
            "planning_request": serializer.data
        })

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def allocate_inventory(self, request, pk=None):
        """
        Manually allocate specific quantities of inventory to planning request items.

        Request body:
        {
            "allocations": [
                {
                    "planning_request_item_id": 1,
                    "allocated_quantity": "10.00",
                    "notes": "Optional notes"
                },
                ...
            ]
        }
        """
        planning_request = self.get_object()
        user = request.user

        # Only planning team can allocate
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can allocate inventory."}, status=403)

        if not planning_request.check_inventory:
            return Response(
                {"detail": "This planning request doesn't have inventory control enabled."},
                status=400
            )

        # Add planning_request_id to the data
        data = request.data.copy()
        data['planning_request_id'] = planning_request.id

        serializer = AllocateInventorySerializer(data=data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        result = serializer.save()

        # Refresh planning request to get updated status
        planning_request.refresh_from_db()
        pr_serializer = self.get_serializer(planning_request)

        return Response({
            "detail": f"Successfully allocated inventory for {result['count']} items.",
            "allocations": InventoryAllocationSerializer(result['allocations'], many=True).data,
            "planning_request": pr_serializer.data
        }, status=201)

    @action(detail=True, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def inventory_allocations(self, request, pk=None):
        """
        Get all inventory allocations for this planning request.
        """
        planning_request = self.get_object()

        allocations = InventoryAllocation.objects.filter(
            planning_request_item__planning_request=planning_request
        ).select_related(
            'planning_request_item__item',
            'allocated_by'
        ).order_by('-allocated_at')

        serializer = InventoryAllocationSerializer(allocations, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def complete_inventory_control(self, request, pk=None):
        """
        Mark inventory control as completed for this planning request.

        After allocating inventory (either manually or via auto_allocate_inventory),
        call this endpoint to finalize the inventory control process.

        Logic:
        - If ALL items are fulfilled from inventory → status='completed' (not available for procurement)
        - If SOME/NO items from inventory → status='ready' (available for procurement)

        Request body example:
        {
            "allocations": [
                {
                    "planning_request_item_id": 1,
                    "allocated_quantity": "5.00",
                    "notes": "Found 5 in warehouse A"
                },
                {
                    "planning_request_item_id": 2,
                    "allocated_quantity": "0.00",
                    "notes": "Not found in inventory"
                }
            ]
        }

        Or if you already allocated using auto_allocate_inventory or allocate_inventory,
        just send empty body: {}
        """
        planning_request = self.get_object()
        user = request.user

        # Only planning team can complete inventory control
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can complete inventory control."}, status=403)

        if not planning_request.check_inventory:
            return Response(
                {"detail": "This planning request doesn't have inventory control enabled."},
                status=400
            )

        # If allocations provided, create them first
        allocations_data = request.data.get('allocations', [])
        if allocations_data:
            # Add planning_request_id to the data
            data = {
                'planning_request_id': planning_request.id,
                'allocations': allocations_data
            }

            serializer = AllocateInventorySerializer(data=data, context={'request': request})
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)

            allocation_result = serializer.save()
            allocations_created = allocation_result['count']
        else:
            allocations_created = 0

        # Complete the inventory control
        try:
            result = planning_request.complete_inventory_control()
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        # Refresh and serialize
        planning_request.refresh_from_db()
        pr_serializer = self.get_serializer(planning_request)

        return Response({
            "detail": result['message'],
            "status": result['status'],
            "fully_from_inventory": result['fully_from_inventory'],
            "allocations_created": allocations_created,
            "planning_request": pr_serializer.data
        })

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def mark_ready_for_procurement(self, request, pk=None):
        """
        Mark planning request as ready for procurement after ERP entry.
        Planning team calls this after entering items into ERP system.

        Request body:
        {
            "erp_code": "ERP-2024-12345",
            "request_number": "GS-12345"  // optional
        }
        """
        planning_request = self.get_object()
        user = request.user

        # Only planning team can mark as ready
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response({"detail": "Only planning team can mark requests as ready for procurement."}, status=403)

        erp_code = request.data.get('erp_code', '').strip()
        if not erp_code:
            return Response({"detail": "ERP code is required."}, status=400)

        request_number = request.data.get('request_number', '').strip() or None

        try:
            result = planning_request.mark_ready_for_procurement(erp_code, request_number=request_number)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        # Refresh and serialize
        planning_request.refresh_from_db()
        pr_serializer = self.get_serializer(planning_request)

        return Response({
            "detail": result['message'],
            "status": result['status'],
            "request_number": result['request_number'],
            "erp_code": result['erp_code'],
            "planning_request": pr_serializer.data
        })

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated], url_path='attachments')
    def upload_attachment(self, request, pk=None):
        """Upload and attach a file to this planning request."""
        planning_request = self.get_object()
        upload_serializer = AttachmentUploadSerializer(data=request.data)
        if not upload_serializer.is_valid():
            return Response(upload_serializer.errors, status=400)

        attachment = _create_attachment_for_target(planning_request, upload_serializer.validated_data, request.user)
        return Response(FileAttachmentSerializer(attachment, context={'request': request}).data, status=201)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def update_inventory_quantities(self, request, pk=None):
        """
        Simple endpoint to update inventory found quantities.
        Updates quantity_from_inventory and quantity_to_purchase for each item.

        Request body:
        {
            "items": [
                {
                    "planning_request_item_id": 1,
                    "quantity_found": "10.00"
                },
                {
                    "planning_request_item_id": 2,
                    "quantity_found": "0.00"
                }
            ]
        }
        """
        planning_request = self.get_object()
        user = request.user

        # Only warehouse team and superusers can update inventory quantities
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'warehouse')):
            return Response(
                {"detail": "Only warehouse team can update inventory quantities."},
                status=403
            )

        serializer = UpdateInventoryQuantitiesSerializer(
            data=request.data,
            context={'planning_request_id': planning_request.id, 'request': request}
        )

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        result = serializer.update_quantities()

        # Refresh and serialize
        planning_request.refresh_from_db()
        pr_serializer = self.get_serializer(planning_request)

        return Response({
            "detail": f"Successfully updated inventory quantities for {result['count']} items.",
            "updated_count": result['count'],
            "planning_request": pr_serializer.data
        })

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

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def warehouse_requests(self, request):
        """
        Get planning requests for warehouse team.
        Shows requests that need inventory checking or have been submitted.

        Query parameters:
        - status: Filter by specific status (pending_inventory, pending_erp_entry, completed)
        - If no status provided, shows all requests with check_inventory=True
        """
        user = request.user

        # Only warehouse team and superusers can access
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'warehouse')):
            return Response({"detail": "Only warehouse team can access this endpoint."}, status=403)

        # Base queryset: all requests with inventory control enabled
        queryset = self.get_queryset().filter(check_inventory=True)

        # Filter by status if provided
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Order by priority and creation date
        queryset = queryset.order_by('-priority', '-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def cancel(self, request, pk=None):  # noqa: ARG002
        """
        Cancel a planning request.

        Only planning team can cancel requests.
        Cannot cancel requests that are already converted or completed.

        Request body:
        {
            "cancellation_reason": "Reason for cancellation"
        }
        """
        planning_request = self.get_object()
        user = request.user

        # Only planning team can cancel
        if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
            return Response(
                {"detail": "Only planning team can cancel planning requests."},
                status=403
            )

        # Cannot cancel if already converted or completed
        if planning_request.status in ['converted', 'completed', 'cancelled']:
            return Response(
                {"detail": f"Cannot cancel planning request with status '{planning_request.status}'."},
                status=400
            )

        # Update status to cancelled
        old_status = planning_request.status
        planning_request.status = 'cancelled'
        planning_request.save(update_fields=['status'])

        # Refresh and serialize
        planning_request.refresh_from_db()
        pr_serializer = self.get_serializer(planning_request)

        return Response({
            "detail": f"Planning request cancelled. Previous status: {old_status}",
            "planning_request": pr_serializer.data
        })


class PlanningRequestItemViewSet(viewsets.ModelViewSet):
    """
    Manage individual items within a planning request.
    Planning team uses this to map department request items to catalog items.
    """
    queryset = PlanningRequestItem.objects.all()
    serializer_class = PlanningRequestItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PlanningRequestItemFilter
    ordering_fields = ['order', 'id',]
    ordering = ['id']

    def get_queryset(self):
        from django.db.models import Count

        # For list views, use minimal prefetching
        if self.action == 'list':
            qs = PlanningRequestItem.objects.select_related(
                'planning_request', 'item'
            ).annotate(
                files_count=Count('files')
            )
        else:
            # For detail views, prefetch all related data
            qs = PlanningRequestItem.objects.select_related(
                'planning_request', 'item'
            ).prefetch_related(
                Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment'))
            )

        # Filter by planning_request param if provided
        pr_id = self.request.query_params.get('planning_request')
        if pr_id:
            qs = qs.filter(planning_request_id=pr_id)

        # All authenticated users can view (GET requests)
        # Restrictions for write operations are handled in get_permissions()
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return PlanningRequestItemListSerializer
        return PlanningRequestItemSerializer

    def get_permissions(self):
        """
        Allow all authenticated users to view (GET, list, retrieve).
        Only planning team and superusers can create, update, or delete.
        """
        permission_classes = [permissions.IsAuthenticated]

        # For write operations, require planning team or superuser
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'bulk_create', 'upload_attachment']:
            permission_classes.append(permissions.IsAdminUser)

        return [permission() for permission in permission_classes]

    def check_permissions(self, request):
        """Override to add custom team-based permission check for write operations."""
        super().check_permissions(request)

        # For write operations, check if user is planning team or superuser
        if self.action in ['create', 'update', 'partial_update', 'destroy', 'bulk_create', 'upload_attachment']:
            user = request.user
            if not (user.is_superuser or (hasattr(user, 'profile') and user.profile.team == 'planning')):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied("Only planning team members can perform this action.")

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

    @action(detail=True, methods=['POST'], permission_classes=[CanMarkDelivered], url_path='mark_delivered')
    def mark_delivered(self, request, pk=None):
        """Mark a single PlanningRequestItem as delivered."""
        from django.utils import timezone

        item = self.get_object()
        if item.is_delivered:
            return Response({"detail": "Item is already marked as delivered."}, status=400)

        item.is_delivered = True
        item.delivered_at = timezone.now()
        item.delivered_by = request.user
        item.save(update_fields=['is_delivered', 'delivered_at', 'delivered_by'])

        serializer = self.get_serializer(item)
        return Response(serializer.data)

    @action(detail=False, methods=['POST'], permission_classes=[CanMarkDelivered], url_path='bulk_mark_delivered')
    def bulk_mark_delivered(self, request):
        """
        Mark multiple PlanningRequestItems as delivered.

        Request body:
        {
            "ids": [1, 2, 3]
        }
        """
        from django.utils import timezone

        ids = request.data.get('ids', [])
        if not ids or not isinstance(ids, list):
            return Response({"detail": "ids is required and must be a non-empty list."}, status=400)

        now = timezone.now()
        items = PlanningRequestItem.objects.filter(id__in=ids, is_delivered=False)
        updated = items.update(is_delivered=True, delivered_at=now, delivered_by=request.user)

        return Response({
            "detail": f"Marked {updated} items as delivered.",
            "updated_count": updated,
        })

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def available_count(self, request):
        """
        Get simple count of available planning request items.
        Lightweight endpoint for info bubbles and quick stats.

        Query parameters:
        - planning_request: Filter by specific planning request ID
        - Any other filter from PlanningRequestItemFilter

        Returns:
        {
            "count": 45
        }
        """
        from django.db.models import Q, Sum, OuterRef, Subquery, Value, F
        from django.db.models.functions import Coalesce, Greatest
        from decimal import Decimal
        from procurement.models import PurchaseRequestItem

        # Start with filtered queryset
        qs = self.filter_queryset(self.get_queryset())

        # FK path: PurchaseRequestItems directly linked via planning_request_item FK
        qty_via_fk = PurchaseRequestItem.objects.filter(
            planning_request_item=OuterRef('pk')
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('planning_request_item').annotate(
            total=Sum('quantity')
        ).values('total')

        # M2M path: PurchaseRequestItems in PRs linked via M2M, matching by item_id
        qty_via_m2m = PurchaseRequestItem.objects.filter(
            purchase_request__planning_request_items=OuterRef('pk'),
            item_id=OuterRef('item_id'),
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('item_id').annotate(
            total=Sum('quantity')
        ).values('total')

        zero = Value(Decimal('0.00'))

        qs = qs.annotate(
            _qty_in_prs=Greatest(
                Coalesce(Subquery(qty_via_fk), zero),
                Coalesce(Subquery(qty_via_m2m), zero),
            ),
        )

        # Count items with remaining quantity available
        available_count = qs.filter(
            Q(planning_request__status='ready') | Q(planning_request__status='converted'),
            quantity_to_purchase__gt=F('_qty_in_prs')
        ).count()

        return Response({
            "count": available_count
        })

    @action(detail=False, methods=['GET'], permission_classes=[permissions.IsAuthenticated])
    def availability_stats(self, request):
        """
        Get statistics about planning request items availability.

        Query parameters:
        - planning_request: Filter by specific planning request ID

        Returns:
        {
            "total_items": 100,
            "available_items": 45,
            "unavailable_items": 55,
            "availability_percentage": 45.0
        }
        """
        from django.db.models import Q, Sum, OuterRef, Subquery, Value, F, Count, Case, When, IntegerField
        from django.db.models.functions import Coalesce, Greatest
        from decimal import Decimal
        from procurement.models import PurchaseRequestItem

        # Start with filtered queryset
        qs = self.filter_queryset(self.get_queryset())

        # Count total items
        total_items = qs.count()

        if total_items == 0:
            return Response({
                "total_items": 0,
                "available_items": 0,
                "unavailable_items": 0,
                "availability_percentage": 0.0
            })

        # FK path: PurchaseRequestItems directly linked via planning_request_item FK
        qty_via_fk = PurchaseRequestItem.objects.filter(
            planning_request_item=OuterRef('pk')
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('planning_request_item').annotate(
            total=Sum('quantity')
        ).values('total')

        # M2M path: PurchaseRequestItems in PRs linked via M2M, matching by item_id
        qty_via_m2m = PurchaseRequestItem.objects.filter(
            purchase_request__planning_request_items=OuterRef('pk'),
            item_id=OuterRef('item_id'),
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('item_id').annotate(
            total=Sum('quantity')
        ).values('total')

        zero = Value(Decimal('0.00'))

        qs = qs.annotate(
            _qty_in_prs=Greatest(
                Coalesce(Subquery(qty_via_fk), zero),
                Coalesce(Subquery(qty_via_m2m), zero),
            ),
        )

        # Count available: ready/converted status AND has remaining quantity
        is_available = (
            Q(planning_request__status='ready') | Q(planning_request__status='converted')
        ) & Q(quantity_to_purchase__gt=F('_qty_in_prs'))

        stats = qs.aggregate(
            available_items=Count(
                Case(When(is_available, then=1), output_field=IntegerField())
            ),
            unavailable_items=Count(
                Case(When(~is_available, then=1), output_field=IntegerField())
            )
        )

        available_items = stats['available_items'] or 0
        unavailable_items = stats['unavailable_items'] or 0
        availability_percentage = round((available_items / total_items * 100), 2) if total_items > 0 else 0.0

        return Response({
            "total_items": total_items,
            "available_items": available_items,
            "unavailable_items": unavailable_items,
            "availability_percentage": availability_percentage
        })

    @action(detail=False, methods=['POST'], permission_classes=[permissions.IsAuthenticated])
    def bulk_files(self, request):
        """
        Get all files for multiple planning request items at once.

        Request body:
        {
            "item_ids": [203, 208, 307]
        }

        Returns:
        {
            "files": [
                {
                    "item_id": 203,
                    "item_code": "PIPE-2IN",
                    "files": [...]
                },
                ...
            ],
            "total_files": 15
        }
        """
        item_ids = request.data.get('item_ids', [])

        if not item_ids:
            return Response({"detail": "item_ids is required and must be a non-empty list."}, status=400)

        if not isinstance(item_ids, list):
            return Response({"detail": "item_ids must be a list."}, status=400)

        # Get items with their files
        items = PlanningRequestItem.objects.filter(
            id__in=item_ids
        ).select_related('item').prefetch_related(
            Prefetch('files', queryset=FileAttachment.objects.select_related('asset', 'uploaded_by', 'source_attachment'))
        )

        # Build response
        result = []
        total_files = 0

        for item in items:
            files_data = FileAttachmentSerializer(item.files.all(), many=True, context={'request': request}).data
            total_files += len(files_data)

            result.append({
                'item_id': item.id,
                'item_code': item.item.code if item.item else None,
                'item_name': item.item.name if item.item else None,
                'job_no': item.job_no,
                'files': files_data
            })

        return Response({
            'items': result,
            'total_files': total_files,
            'requested_count': len(item_ids),
            'found_count': len(result)
        })


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
