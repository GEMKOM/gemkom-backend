import time
import logging
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework import viewsets, mixins
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from users.permissions import IsCuttingUserOrAdmin, IsOfficeUserOrAdmin
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action

logger = logging.getLogger(__name__)

from .models import CncTask, CncPart, RemnantPlate
from tasks.models import TaskFile
from tasks.views import (
    GenericTimerDetailView,
    GenericTimerListView,
    GenericTimerManualEntryView,
    GenericTimerReportView,
    GenericTimerStartView,
    GenericTimerStopView,
    GenericMarkTaskCompletedView,
    GenericUnmarkTaskCompletedView,
    GenericPlanningListView,
    GenericProductionPlanView,
    GenericPlanningBulkSaveView,
)
from .serializers import (
    CncTaskListSerializer,
    CncTaskDetailSerializer,
    CncPartSerializer,
    CncPartSearchResultSerializer,
    CncTimerSerializer,
    RemnantPlateSerializer,
    CncPlanningListItemSerializer,
    CncProductionPlanSerializer,
    CncTaskPlanUpdateItemSerializer,
    CncTaskPlanBulkListSerializer,
)
from .serializers import CncHoldTaskSerializer
from .filters import CncTaskFilter, RemnantPlateFilter
from tasks.serializers import TaskFileSerializer
from tasks.view_mixins import TaskFileMixin

class TimerStartView(GenericTimerStartView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='cnc_cutting')

class TimerStopView(GenericTimerStopView):
    permission_classes = [IsAuthenticated]

class TimerManualEntryView(GenericTimerManualEntryView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        return super().post(request, task_type='cnc_cutting')

class TimerListView(GenericTimerListView):
    permission_classes = [IsAuthenticated]
    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='cnc_cutting')

class TimerDetailView(GenericTimerDetailView):
    permission_classes = [IsAuthenticated]

class TimerReportView(GenericTimerReportView):
    permission_classes = [IsOfficeUserOrAdmin]
    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='cnc_cutting')

class MarkTaskCompletedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')


class UnmarkTaskCompletedView(GenericUnmarkTaskCompletedView):
    permission_classes = [IsCuttingUserOrAdmin]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')

class MarkTaskWareHouseProcessedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        task_key = request.data.get('key')
        if not task_key:
            return Response({'error': 'Task key is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            task = CncTask.objects.get(key=task_key)
            task.processed_by_warehouse = True
            task.processed_warehouse_date = timezone.now().date()
            task.save()
            return Response({'status': 'Task marked as processed by warehouse.'}, status=status.HTTP_200_OK)
        except CncTask.DoesNotExist:
            return Response({'error': 'Task not found.'}, status=status.HTTP_404_NOT_FOUND)
# --- Planning Views ---

class PlanningListView(GenericPlanningListView):
    """
    GET /cnc_cutting/planning/list/?machine_fk=...
    """
    permission_classes = [IsAuthenticated]
    task_model = CncTask
    serializer_class = CncPlanningListItemSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CncTaskFilter
    ordering_fields = ['key', 'name', 'nesting_id', 'material', 'thickness_mm', 'completion_date', 'estimated_hours', 'plan_order']
    ordering = ['-key']
    resource_fk_field = 'machine_fk'

class ProductionPlanView(GenericProductionPlanView):
    """
    GET /cnc_cutting/planning/production-plan/?machine_fk=...
    """
    permission_classes = [IsAuthenticated]
    task_model = CncTask
    serializer_class = CncProductionPlanSerializer
    resource_fk_field = 'machine_fk'

class PlanningBulkSaveView(GenericPlanningBulkSaveView):
    """
    POST /cnc_cutting/planning/bulk-save/
    """
    permission_classes = [IsOfficeUserOrAdmin] # Planning updates are typically restricted
    task_model = CncTask
    item_serializer_class = CncTaskPlanUpdateItemSerializer
    bulk_list_serializer_class = CncTaskPlanBulkListSerializer
    response_serializer_class = CncPlanningListItemSerializer
    resource_fk_field = 'machine_fk'


class CncTaskViewSet(TaskFileMixin, ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting CNC tasks.
    Handles multipart/form-data for file uploads.
    """
    # Combine querysets for both list and detail views for efficiency
    queryset = CncTask.objects.select_related('machine_fk').prefetch_related('issue_key', 'parts', 'files', 'plate_usage_records__remnant_plate').annotate(parts_count=Count('parts')).order_by('-key')
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # Important for file uploads
    filterset_class = CncTaskFilter
    ordering_fields = ['key', 'name', 'nesting_id', 'material', 'thickness_mm', 'completion_date', 'estimated_hours', 'plan_order']
    ordering = ['-key']
    
    def get_serializer_class(self):
        """
        Return the appropriate serializer class based on the action.
        - CncTaskListSerializer for the 'list' action.
        - CncTaskDetailSerializer for all other actions (create, retrieve, update).
        """
        if self.action == 'list':
            return CncTaskListSerializer
        return CncTaskDetailSerializer
    
    def get_queryset(self):
        # 'issue_key' is the GenericRelation from tasks.Timer back to this Task
        # prefetch_related works seamlessly with it for great performance.
        return CncTask.objects.filter(is_hold_task=False)


class CncHoldTaskViewSet(ModelViewSet):
    """
    ViewSet for listing CNC hold tasks.
    """
    queryset = CncTask.objects.all()
    serializer_class = CncHoldTaskSerializer
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticated]
    filterset_class = CncTaskFilter

    def get_queryset(self):
        return CncTask.objects.filter(is_hold_task=True)

class CncPartViewSet(ModelViewSet):
    """
    ViewSet for creating, retrieving, updating, and deleting CncPart instances.
    """
    queryset = CncPart.objects.all()
    serializer_class = CncPartSerializer
    permission_classes = [IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        """
        Delete a single CncPart instance.
        Only office users can delete parts.
        """
        # Authorization: Only office users can delete parts
        user = request.user
        if not (user and hasattr(user, 'profile') and user.profile.work_location == 'office'):
            return Response(
                {"error": "Only office users can delete parts."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get the part to delete
        part = self.get_object()

        # Log the deletion
        logger.info(
            f"Deleting part: User={user.username}, PartID={part.id}, "
            f"Task={part.cnc_task.key}, JobNo={part.job_no}, "
            f"ImageNo={part.image_no}, PositionNo={part.position_no}"
        )

        # Perform deletion
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request, *args, **kwargs):
        """
        Handles bulk creation of CncPart instances.
        Expects a POST request to `/api/cnc_cutting/parts/bulk-create/`
        with a list of CncPart objects in the request body.
        """
        # Ensure the serializer handles multiple objects
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        
        # Save all valid instances
        instances = serializer.save()
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=False, methods=['delete'], url_path='bulk-delete')
    def bulk_delete(self, request, *args, **kwargs):
        """
        Handles bulk deletion of CncPart instances for a single CNC task.
        Expects a DELETE request to `/api/cnc_cutting/parts/bulk-delete/`
        with a task key and list of CncPart IDs in the request body.
        e.g. {"task_key": "CNC-001", "ids": [1, 2, 3]}

        Restrictions:
        - Only office users can delete parts
        - All parts must belong to the specified task
        - Only deletes parts from a single task at a time
        """
        # Authorization: Only office users can bulk delete parts
        user = request.user
        if not (user and hasattr(user, 'profile') and user.profile.work_location == 'office'):
            return Response(
                {"error": "Only office users can bulk delete parts."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get and validate task_key
        task_key = request.data.get('task_key')
        if not task_key or not isinstance(task_key, str):
            return Response(
                {"error": "A valid 'task_key' string is required in the request body."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get and validate part IDs
        part_ids = request.data.get('ids')
        if part_ids is None:
            return Response(
                {"error": "The 'ids' field is required in the request body."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not isinstance(part_ids, list):
            return Response(
                {"error": "The 'ids' field must be a list of part IDs."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not part_ids:
            return Response(
                {"error": "The 'ids' list cannot be empty."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate all IDs are integers
        if not all(isinstance(id, int) for id in part_ids):
            return Response(
                {"error": "All part IDs must be integers."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify the task exists
        try:
            task = CncTask.objects.get(key=task_key)
        except CncTask.DoesNotExist:
            return Response(
                {"error": f"CNC task '{task_key}' not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Filter parts that belong to this specific task
        parts_to_delete = CncPart.objects.filter(
            id__in=part_ids,
            cnc_task=task
        )

        # Check if all requested parts were found and belong to the task
        found_count = parts_to_delete.count()
        if found_count != len(part_ids):
            missing_or_wrong_task = set(part_ids) - set(parts_to_delete.values_list('id', flat=True))
            logger.warning(
                f"Bulk delete failed - invalid part IDs: User={user.username}, "
                f"Task={task_key}, RequestedIDs={part_ids}, InvalidIDs={list(missing_or_wrong_task)}"
            )
            return Response(
                {
                    "error": f"Some part IDs were not found or do not belong to task '{task_key}'.",
                    "invalid_ids": list(missing_or_wrong_task)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Log the deletion before performing it (for audit trail)
        parts_info = list(parts_to_delete.values('id', 'job_no', 'image_no', 'position_no'))
        logger.info(
            f"Bulk deleting {found_count} parts: User={user.username}, "
            f"Task={task_key}, PartIDs={part_ids}, Parts={parts_info}"
        )

        # Perform deletion
        count, _ = parts_to_delete.delete()

        logger.info(
            f"Successfully bulk deleted {count} parts: User={user.username}, Task={task_key}"
        )

        return Response({
            'status': f'{count} parts deleted successfully from task {task_key}.',
            'deleted_count': count,
            'task_key': task_key
        }, status=status.HTTP_200_OK)

class CncTaskFileViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    ViewSet for deleting a TaskFile.
    """
    queryset = TaskFile.objects.all()
    serializer_class = TaskFileSerializer
    permission_classes = [IsAuthenticated]

class RemnantPlateViewSet(ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting RemnantPlate instances.
    """
    queryset = RemnantPlate.objects.all()
    serializer_class = RemnantPlateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = RemnantPlateFilter
    ordering_fields = ['thickness_mm', 'dimensions', 'quantity', 'material', 'heat_number']
    ordering = ['-id']

    def get_queryset(self):
        """
        By default, for 'list' actions, only show remnant plates that have available quantity
        (i.e., not fully consumed by tasks). This can be changed by using the `unassigned` filter.
        For other actions (retrieve, update, delete), allow access to any remnant plate.
        """
        qs = super().get_queryset()
        if self.action == 'list':
            # Default to showing only plates with available quantity if no specific filter is given.
            if 'unassigned' not in self.request.query_params:
                # Only show plates where the available quantity is greater than 0
                # This requires annotating with usage count and comparing to total quantity
                from django.db.models import Sum, F, Q
                qs = qs.annotate(
                    total_used=Sum('usage_records__quantity_used')
                ).filter(
                    Q(total_used__isnull=True) | Q(total_used__lt=F('quantity'))
                )
        return qs

    @action(detail=False, methods=['post'], url_path='bulk-create')
    def bulk_create(self, request, *args, **kwargs):
        """
        Handles bulk creation of RemnantPlate instances.
        Expects a POST request to `/api/cnc_cutting/remnants/bulk-create/`
        with a list of remnant plate objects in the request body.
        """
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        instances = serializer.save()
        response_serializer = self.get_serializer(instances, many=True)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CncPartSearchPagination(PageNumberPagination):
    """Custom pagination for CNC part search results."""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class CncPartSearchView(ListAPIView):
    """
    API view for searching CNC parts by job_no, image_no, and position_no.
    Supports partial matching on all fields and returns the associated CNC task details.
    Returns all parts if no filters are provided (paginated).

    GET /api/cnc_cutting/parts/search/?job_no=...&image_no=...&position_no=...
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CncPartSearchResultSerializer
    pagination_class = CncPartSearchPagination

    def get_queryset(self):
        """
        Search for CNC parts with optional partial filters.
        Query parameters:
        - job_no: Partial match on job number
        - image_no: Partial match on image number
        - position_no: Partial match on position number

        If no filters are provided, returns all parts (paginated).
        """
        queryset = CncPart.objects.select_related('cnc_task').all().order_by('-id')

        # Apply filters if provided
        job_no = self.request.query_params.get('job_no', None)
        image_no = self.request.query_params.get('image_no', None)
        position_no = self.request.query_params.get('position_no', None)

        if job_no:
            queryset = queryset.filter(job_no__icontains=job_no)

        if image_no:
            queryset = queryset.filter(image_no__icontains=image_no)

        if position_no:
            queryset = queryset.filter(position_no__icontains=position_no)

        return queryset
