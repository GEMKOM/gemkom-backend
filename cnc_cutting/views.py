from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from .models import CncTask
from .serializers import CncTaskSerializer

class CncTaskListCreateView(ListCreateAPIView):
    """
    API view to list all CNC tasks or create a new one.
    Handles multipart/form-data for file uploads.
    """
    queryset = CncTask.objects.all().order_by('-key')
    serializer_class = CncTaskSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] # Important for file uploads


class CncTaskDetailView(RetrieveUpdateDestroyAPIView):
    """
    API view to retrieve, update, or delete a single CNC task.
    """
    queryset = CncTask.objects.all()
    serializer_class = CncTaskSerializer
    permission_classes = [IsAuthenticated]