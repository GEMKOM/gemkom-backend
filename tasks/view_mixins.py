from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from .models import TaskFile
from .serializers import TaskFileSerializer

class TaskFileMixin:
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser], url_path='add-file')
    def add_file(self, request, pk=None):
        """
        Upload one or more files to an existing task.
        """
        task = self.get_object()
        uploaded_files = request.FILES.getlist('files')
        
        if not uploaded_files:
            return Response({"error": "No files provided in the 'files' field."}, status=status.HTTP_400_BAD_REQUEST)

        created_file_instances = []
        for file in uploaded_files:
            instance = TaskFile.objects.create(task=task, file=file, uploaded_by=request.user)
            created_file_instances.append(instance)

        serializer = TaskFileSerializer(created_file_instances, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
