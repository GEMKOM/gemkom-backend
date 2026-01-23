from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES
)
from .serializers import (
    CustomerListSerializer,
    CustomerDetailSerializer,
    CustomerCreateUpdateSerializer,
    JobOrderListSerializer,
    JobOrderDetailSerializer,
    JobOrderCreateSerializer,
    JobOrderUpdateSerializer,
    JobOrderFileSerializer,
    JobOrderFileUploadSerializer,
    DepartmentTaskTemplateListSerializer,
    DepartmentTaskTemplateDetailSerializer,
    DepartmentTaskTemplateCreateUpdateSerializer,
    DepartmentTaskTemplateItemSerializer,
    DepartmentTaskListSerializer,
    DepartmentTaskDetailSerializer,
    DepartmentTaskCreateSerializer,
    DepartmentTaskUpdateSerializer,
    ApplyTemplateSerializer,
)


class CustomerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Customer CRUD operations.

    List: Returns lightweight CustomerListSerializer
    Retrieve: Returns full CustomerDetailSerializer
    Create/Update: Uses CustomerCreateUpdateSerializer
    """
    queryset = Customer.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['code', 'name', 'short_name', 'contact_person', 'email']
    ordering_fields = ['code', 'name', 'created_at', 'updated_at']
    ordering = ['code']
    filterset_fields = {
        'is_active': ['exact'],
        'default_currency': ['exact'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        elif self.action == 'retrieve':
            return CustomerDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return CustomerCreateUpdateSerializer
        return CustomerDetailSerializer

    def get_queryset(self):
        queryset = Customer.objects.all()
        # By default, only show active customers unless explicitly requested
        show_inactive = self.request.query_params.get('show_inactive', 'false').lower() == 'true'
        if not show_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return detail serializer for the created object
        detail_serializer = CustomerDetailSerializer(serializer.instance)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Return detail serializer for the updated object
        detail_serializer = CustomerDetailSerializer(serializer.instance)
        return Response(detail_serializer.data)


class JobOrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for JobOrder CRUD operations with workflow actions.

    List: Returns lightweight JobOrderListSerializer
    Retrieve: Returns full JobOrderDetailSerializer with children
    Create: Uses JobOrderCreateSerializer
    Update: Uses JobOrderUpdateSerializer

    Custom Actions:
    - POST /job-orders/{job_no}/start/ - Start the job (draft -> active)
    - POST /job-orders/{job_no}/complete/ - Complete the job
    - POST /job-orders/{job_no}/hold/ - Put job on hold
    - POST /job-orders/{job_no}/resume/ - Resume from hold
    - POST /job-orders/{job_no}/cancel/ - Cancel the job
    - GET /job-orders/{job_no}/hierarchy/ - Get full hierarchy tree
    """
    queryset = JobOrder.objects.select_related('customer', 'parent', 'created_by', 'completed_by')
    lookup_field = 'job_no'
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['job_no', 'title', 'description', 'customer__name', 'customer__code']
    ordering_fields = ['job_no', 'title', 'status', 'priority', 'target_completion_date', 'created_at']
    ordering = ['-created_at']
    filterset_fields = {
        'status': ['exact', 'in'],
        'priority': ['exact', 'in'],
        'customer': ['exact'],
        'parent': ['exact', 'isnull'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return JobOrderListSerializer
        elif self.action == 'retrieve':
            return JobOrderDetailSerializer
        elif self.action == 'create':
            return JobOrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return JobOrderUpdateSerializer
        return JobOrderDetailSerializer

    def get_queryset(self):
        queryset = JobOrder.objects.select_related(
            'customer', 'parent', 'created_by', 'completed_by'
        ).prefetch_related('children')

        # Filter by root only (no parent) if requested
        root_only = self.request.query_params.get('root_only', 'false').lower() == 'true'
        if root_only:
            queryset = queryset.filter(parent__isnull=True)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return detail serializer for the created object
        detail_serializer = JobOrderDetailSerializer(serializer.instance)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Return detail serializer for the updated object
        detail_serializer = JobOrderDetailSerializer(serializer.instance)
        return Response(detail_serializer.data)

    # -------------------------------------------------------------------------
    # Workflow Actions
    # -------------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def start(self, request, job_no=None):
        """Start the job order (draft -> active)."""
        job_order = self.get_object()
        try:
            job_order.start(user=request.user)
            return Response({
                'status': 'success',
                'message': 'İş emri başlatıldı.',
                'job_order': JobOrderDetailSerializer(job_order).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def hold(self, request, job_no=None):
        """Put the job order on hold."""
        job_order = self.get_object()
        reason = request.data.get('reason', '')
        try:
            job_order.hold(reason=reason)
            return Response({
                'status': 'success',
                'message': 'İş emri beklemeye alındı.',
                'job_order': JobOrderDetailSerializer(job_order).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def resume(self, request, job_no=None):
        """Resume the job order from hold."""
        job_order = self.get_object()
        try:
            job_order.resume()
            return Response({
                'status': 'success',
                'message': 'İş emri devam ettirildi.',
                'job_order': JobOrderDetailSerializer(job_order).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def cancel(self, request, job_no=None):
        """Cancel the job order."""
        job_order = self.get_object()
        try:
            job_order.cancel(user=request.user)
            return Response({
                'status': 'success',
                'message': 'İş emri iptal edildi.',
                'job_order': JobOrderDetailSerializer(job_order).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'])
    def hierarchy(self, request, job_no=None):
        """
        Get the full hierarchy tree for a job order.
        Returns the root job with all descendants nested.
        """
        job_order = self.get_object()

        # Find root
        root = job_order
        while root.parent:
            root = root.parent

        def build_tree(job):
            """Recursively build hierarchy tree."""
            children_data = []
            for child in job.children.all():
                children_data.append(build_tree(child))

            # Get department tasks (main tasks only)
            dept_tasks = job.department_tasks.filter(parent__isnull=True).order_by('sequence')
            dept_tasks_data = [
                {
                    'id': task.id,
                    'department': task.department,
                    'department_display': task.get_department_display(),
                    'title': task.title,
                    'status': task.status,
                    'status_display': task.get_status_display(),
                    'sequence': task.sequence,
                    'can_start': task.can_start(),
                    'assigned_to_name': task.assigned_to.get_full_name() if task.assigned_to else None,
                }
                for task in dept_tasks
            ]

            return {
                'job_no': job.job_no,
                'title': job.title,
                'status': job.status,
                'status_display': job.get_status_display(),
                'priority': job.priority,
                'completion_percentage': job.completion_percentage,
                'target_completion_date': job.target_completion_date,
                'department_tasks': dept_tasks_data,
                'children': children_data
            }

        return Response(build_tree(root))

    @action(detail=False, methods=['get'])
    def status_choices(self, request):
        """Get available status choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in JobOrder.STATUS_CHOICES
        ])

    @action(detail=False, methods=['get'])
    def priority_choices(self, request):
        """Get available priority choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in JobOrder.PRIORITY_CHOICES
        ])

    @action(detail=True, methods=['post'])
    def apply_template(self, request, job_no=None):
        """Apply a department task template to this job order."""
        job_order = self.get_object()

        # Check if job order already has department tasks
        if job_order.department_tasks.exists():
            return Response(
                {'status': 'error', 'message': 'Bu iş emri zaten departman görevlerine sahip.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ApplyTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created_tasks = serializer.create_tasks_from_template(job_order, request.user)

        return Response({
            'status': 'success',
            'message': f'{len(created_tasks)} departman görevi oluşturuldu.',
            'tasks': DepartmentTaskListSerializer(created_tasks, many=True).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def department_tasks(self, request, job_no=None):
        """Get all department tasks for this job order."""
        job_order = self.get_object()
        # Only return main tasks (no parent), subtasks are nested
        tasks = job_order.department_tasks.filter(parent__isnull=True).select_related(
            'assigned_to', 'created_by', 'completed_by'
        ).prefetch_related('subtasks', 'depends_on')

        serializer = DepartmentTaskListSerializer(tasks, many=True)
        return Response(serializer.data)

    # -------------------------------------------------------------------------
    # File Actions
    # -------------------------------------------------------------------------

    @action(detail=True, methods=['get'])
    def files(self, request, job_no=None):
        """Get all files for this job order."""
        job_order = self.get_object()
        files = job_order.files.select_related('uploaded_by')

        # Optional filter by file_type
        file_type = request.query_params.get('file_type')
        if file_type:
            files = files.filter(file_type=file_type)

        serializer = JobOrderFileSerializer(files, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_file(self, request, job_no=None):
        """Upload a file to this job order."""
        job_order = self.get_object()

        serializer = JobOrderFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_obj = serializer.save(
            job_order=job_order,
            uploaded_by=request.user
        )

        return Response({
            'status': 'success',
            'message': 'Dosya yüklendi.',
            'file': JobOrderFileSerializer(file_obj, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='files/(?P<file_id>[^/.]+)')
    def delete_file(self, request, job_no=None, file_id=None):
        """Delete a file from this job order."""
        job_order = self.get_object()

        try:
            file_obj = job_order.files.get(pk=file_id)
        except JobOrderFile.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Dosya bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        file_obj.file.delete()  # Delete the actual file
        file_obj.delete()  # Delete the database record

        return Response({
            'status': 'success',
            'message': 'Dosya silindi.'
        })

    @action(detail=False, methods=['get'])
    def file_type_choices(self, request):
        """Get available file type choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in JobOrderFile.FILE_TYPE_CHOICES
        ])


# =============================================================================
# Department Task Template ViewSet
# =============================================================================

class DepartmentTaskTemplateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for DepartmentTaskTemplate CRUD operations.

    Custom Actions:
    - GET /task-templates/{id}/items/ - Get template items
    - POST /task-templates/{id}/items/ - Add item to template
    - DELETE /task-templates/{id}/items/{item_id}/ - Remove item from template
    """
    queryset = DepartmentTaskTemplate.objects.prefetch_related('items')
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']
    filterset_fields = {
        'is_active': ['exact'],
        'is_default': ['exact'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return DepartmentTaskTemplateListSerializer
        elif self.action == 'retrieve':
            return DepartmentTaskTemplateDetailSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return DepartmentTaskTemplateCreateUpdateSerializer
        return DepartmentTaskTemplateDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        detail_serializer = DepartmentTaskTemplateDetailSerializer(serializer.instance)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        detail_serializer = DepartmentTaskTemplateDetailSerializer(serializer.instance)
        return Response(detail_serializer.data)

    @action(detail=True, methods=['get', 'post'])
    def items(self, request, pk=None):
        """Get or add template items."""
        template = self.get_object()

        if request.method == 'GET':
            items = template.items.all()
            serializer = DepartmentTaskTemplateItemSerializer(items, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = DepartmentTaskTemplateItemSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(template=template)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['delete'], url_path='items/(?P<item_id>[^/.]+)')
    def remove_item(self, request, pk=None, item_id=None):
        """Remove an item from template."""
        template = self.get_object()
        try:
            item = template.items.get(id=item_id)
            item.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except DepartmentTaskTemplateItem.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Şablon öğesi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['get'])
    def department_choices(self, request):
        """Get available department choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in DEPARTMENT_CHOICES
        ])


# =============================================================================
# Job Order Department Task ViewSet
# =============================================================================

class JobOrderDepartmentTaskViewSet(viewsets.ModelViewSet):
    """
    ViewSet for JobOrderDepartmentTask CRUD operations with workflow actions.

    Custom Actions:
    - POST /department-tasks/{id}/start/ - Start the task
    - POST /department-tasks/{id}/complete/ - Complete the task
    - POST /department-tasks/{id}/skip/ - Skip the task
    - POST /department-tasks/{id}/uncomplete/ - Revert completed task to in_progress
    """
    queryset = JobOrderDepartmentTask.objects.select_related(
        'job_order', 'assigned_to', 'parent', 'created_by', 'completed_by'
    ).prefetch_related('subtasks', 'depends_on')
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'job_order__job_no', 'job_order__title']
    ordering_fields = ['sequence', 'status', 'created_at', 'target_completion_date']
    ordering = ['job_order', 'sequence']
    filterset_fields = {
        'job_order': ['exact'],
        'department': ['exact', 'in'],
        'status': ['exact', 'in'],
        'assigned_to': ['exact', 'isnull'],
        'parent': ['exact', 'isnull'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return DepartmentTaskListSerializer
        elif self.action == 'retrieve':
            return DepartmentTaskDetailSerializer
        elif self.action == 'create':
            return DepartmentTaskCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return DepartmentTaskUpdateSerializer
        return DepartmentTaskDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filter to main tasks only if requested
        main_only = self.request.query_params.get('main_only', 'false').lower() == 'true'
        if main_only:
            queryset = queryset.filter(parent__isnull=True)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        detail_serializer = DepartmentTaskDetailSerializer(serializer.instance)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        detail_serializer = DepartmentTaskDetailSerializer(serializer.instance)
        return Response(detail_serializer.data)

    # -------------------------------------------------------------------------
    # Workflow Actions
    # -------------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start the department task."""
        task = self.get_object()
        try:
            task.start(user=request.user)
            return Response({
                'status': 'success',
                'message': 'Görev başlatıldı.',
                'task': DepartmentTaskDetailSerializer(task).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Complete the department task."""
        task = self.get_object()
        try:
            task.complete(user=request.user)
            return Response({
                'status': 'success',
                'message': 'Görev tamamlandı.',
                'task': DepartmentTaskDetailSerializer(task).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        """Skip the department task."""
        task = self.get_object()
        try:
            task.skip(user=request.user)
            return Response({
                'status': 'success',
                'message': 'Görev atlandı.',
                'task': DepartmentTaskDetailSerializer(task).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def uncomplete(self, request, pk=None):
        """Revert a completed task back to in_progress."""
        task = self.get_object()
        try:
            task.uncomplete()
            return Response({
                'status': 'success',
                'message': 'Görev tamamlanma durumu geri alındı.',
                'task': DepartmentTaskDetailSerializer(task).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['post'])
    def bulk_create(self, request):
        """
        Create multiple department tasks at once.

        Request body:
        {
            "job_order": 1,
            "tasks": [
                {"department": "design", "sequence": 1},
                {"department": "planning", "sequence": 2},
                {"department": "procurement", "sequence": 3}
            ]
        }
        """
        job_order_id = request.data.get('job_order')
        tasks_data = request.data.get('tasks', [])

        if not job_order_id:
            return Response(
                {'status': 'error', 'message': 'job_order alanı gerekli.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not tasks_data or not isinstance(tasks_data, list):
            return Response(
                {'status': 'error', 'message': 'tasks alanı bir liste olmalıdır.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not JobOrder.objects.filter(pk=job_order_id).exists():
            return Response(
                {'status': 'error', 'message': 'İş emri bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        created_tasks = []
        errors = []

        for idx, task_data in enumerate(tasks_data):
            task_data['job_order'] = job_order_id
            serializer = DepartmentTaskCreateSerializer(data=task_data)
            if serializer.is_valid():
                task = serializer.save(created_by=request.user)
                created_tasks.append(task)
            else:
                errors.append({'index': idx, 'errors': serializer.errors})

        if errors:
            return Response({
                'status': 'partial' if created_tasks else 'error',
                'message': f'{len(created_tasks)} görev oluşturuldu, {len(errors)} hata.',
                'created': DepartmentTaskListSerializer(created_tasks, many=True).data,
                'errors': errors
            }, status=status.HTTP_400_BAD_REQUEST if not created_tasks else status.HTTP_207_MULTI_STATUS)

        return Response({
            'status': 'success',
            'message': f'{len(created_tasks)} görev oluşturuldu.',
            'tasks': DepartmentTaskListSerializer(created_tasks, many=True).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def status_choices(self, request):
        """Get available status choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in JobOrderDepartmentTask.STATUS_CHOICES
        ])

    @action(detail=False, methods=['get'])
    def department_choices(self, request):
        """Get available department choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in DEPARTMENT_CHOICES
        ])
