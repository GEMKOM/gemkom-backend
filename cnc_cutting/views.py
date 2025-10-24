from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from rest_framework import viewsets, mixins

from .models import CncTask, CncPart
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
    CncPlanningListItemSerializer,
    CncProductionPlanSerializer,
    CncTaskPlanUpdateItemSerializer,
    CncTaskPlanBulkListSerializer,
)
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
    permission_classes = [IsAdminUser]
    def get(self, request, *args, **kwargs):
        return super().get(request, task_type='cnc_cutting')

class MarkTaskCompletedView(GenericMarkTaskCompletedView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')


class UnmarkTaskCompletedView(GenericUnmarkTaskCompletedView):
    permission_classes = [IsAdminUser]

    def post(self, request):
        return super().post(request, task_type='cnc_cutting')


# --- Planning Views ---

class PlanningListView(GenericPlanningListView):
    """
    GET /cnc_cutting/planning/list/?machine_fk=...
    """
    permission_classes = [IsAuthenticated] # TODO: Define more specific CNC permissions if needed
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
    permission_classes = [IsAdminUser] # Planning updates are typically restricted
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
    ordering_fields = ['key', 'name', 'nesting_id', 'material', 'thickness_mm', 'completion_date', 'estimated_hours']
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
