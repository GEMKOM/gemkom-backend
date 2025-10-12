from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count
from rest_framework import viewsets, mixins

from .models import CncTask, CncPart
from tasks.models import TaskFile
from .serializers import CncTaskListSerializer, CncTaskDetailSerializer, CncPartSerializer
from tasks.serializers import TaskFileSerializer
from tasks.view_mixins import TaskFileMixin

class CncTaskViewSet(TaskFileMixin, ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting CNC tasks.
    Handles multipart/form-data for file uploads.
    """
    # Combine querysets for both list and detail views for efficiency
    queryset = CncTask.objects.select_related('machine_fk').prefetch_related('issue_key', 'parts', 'files').annotate(parts_count=Count('parts')).order_by('-key')
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # Important for file uploads

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
