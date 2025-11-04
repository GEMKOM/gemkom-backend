import time
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework import viewsets, mixins
from users.permissions import IsCuttingUserOrAdmin, IsOfficeUserOrAdmin
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import action

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
    CncTimerSerializer,
    RemnantPlateSerializer,
    CncPlanningListItemSerializer,
    CncProductionPlanSerializer,
    CncTaskPlanUpdateItemSerializer,
    CncTaskPlanBulkListSerializer,
)
from .serializers import CncHoldTaskSerializer
from .filters import CncTaskFilter
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
    queryset = CncTask.objects.select_related('machine_fk').prefetch_related('issue_key', 'parts', 'files').annotate(parts_count=Count('parts')).order_by('-key')
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
    serializer_class = RemnantPlateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        For 'list' and 'retrieve' actions, only show remnant plates that are not assigned to a task.
        For other actions (update, delete), allow access to any remnant plate.
        """
        return RemnantPlate.objects.filter(assigned_to__isnull=True)
    
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
