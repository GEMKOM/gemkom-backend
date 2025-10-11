from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Count

from .models import CncTask
from .serializers import CncTaskListSerializer, CncTaskDetailSerializer

class CncTaskViewSet(ModelViewSet):
    """
    ViewSet for listing, creating, retrieving, updating, and deleting CNC tasks.
    Handles multipart/form-data for file uploads.
    """
    # Combine querysets for both list and detail views for efficiency
    queryset = CncTask.objects.prefetch_related('issue_key', 'parts', 'files').annotate(parts_count=Count('parts')).order_by('-key')
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