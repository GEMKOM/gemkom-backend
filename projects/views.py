from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES,
    JobOrderDiscussionTopic, JobOrderDiscussionComment,
    DiscussionAttachment, DiscussionNotification
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
    DepartmentTaskTemplateItemUpdateSerializer,
    DepartmentTaskListSerializer,
    DepartmentTaskDetailSerializer,
    DepartmentTaskCreateSerializer,
    DepartmentTaskUpdateSerializer,
    ApplyTemplateSerializer,
    JobOrderDiscussionTopicListSerializer,
    JobOrderDiscussionTopicDetailSerializer,
    JobOrderDiscussionTopicCreateSerializer,
    JobOrderDiscussionTopicUpdateSerializer,
    JobOrderDiscussionCommentListSerializer,
    JobOrderDiscussionCommentDetailSerializer,
    JobOrderDiscussionCommentCreateSerializer,
    JobOrderDiscussionCommentUpdateSerializer,
    DiscussionAttachmentSerializer,
    DiscussionNotificationSerializer,
)
from .permissions import IsOfficeUser, IsTopicOwnerOrReadOnly, IsCommentAuthorOrReadOnly


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

        # For retrieve action, prefetch department tasks with related data
        if self.action == 'retrieve':
            from django.db.models import Prefetch
            queryset = queryset.prefetch_related(
                Prefetch(
                    'department_tasks',
                    queryset=JobOrderDepartmentTask.objects.select_related(
                        'assigned_to', 'job_order'
                    ).filter(parent__isnull=True).order_by('sequence')
                )
            )

        # Filter by root only (no parent) if requested
        root_only = self.request.query_params.get('root_only', 'false').lower() == 'true'
        if root_only:
            queryset = queryset.filter(parent__isnull=True)

        return queryset

    def perform_create(self, serializer):
        job_order = serializer.save(created_by=self.request.user)
        # Auto-start the job order
        job_order.start(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Refresh to get updated status
        serializer.instance.refresh_from_db()
        # Return detail serializer for the created object
        detail_serializer = JobOrderDetailSerializer(serializer.instance, context={'request': request})
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

        # Update task statuses based on dependencies
        for task in created_tasks:
            task.update_status_from_dependencies()

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
        """Get or add template items (main items only, children are nested)."""
        template = self.get_object()

        if request.method == 'GET':
            # Only return main items, children are nested in the serializer
            items = template.items.filter(parent__isnull=True).order_by('sequence')
            serializer = DepartmentTaskTemplateItemSerializer(items, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = DepartmentTaskTemplateItemSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(template=template)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='items/(?P<item_id>[^/.]+)/children')
    def add_child_item(self, request, pk=None, item_id=None):
        """Add a child item to a template item."""
        template = self.get_object()
        try:
            parent_item = template.items.get(id=item_id)
        except DepartmentTaskTemplateItem.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Üst şablon öğesi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Child inherits department from parent
        data = request.data.copy()
        data['department'] = parent_item.department

        serializer = DepartmentTaskTemplateItemSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(template=template, parent=parent_item)

        # Return updated parent with children
        return Response(
            DepartmentTaskTemplateItemSerializer(parent_item).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['delete', 'patch'], url_path='items/(?P<item_id>[^/.]+)')
    def update_or_remove_item(self, request, pk=None, item_id=None):
        """Update or remove an item from template."""
        template = self.get_object()
        try:
            item = template.items.get(id=item_id)
        except DepartmentTaskTemplateItem.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Şablon öğesi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if request.method == 'DELETE':
            item.delete()  # CASCADE will delete children
            return Response(status=status.HTTP_204_NO_CONTENT)

        elif request.method == 'PATCH':
            serializer = DepartmentTaskTemplateItemUpdateSerializer(
                item, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(DepartmentTaskTemplateItemSerializer(item).data)

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

    def list(self, request, *args, **kwargs):
        """Override list to return CNC parts for 'CNC Kesim' parent tasks."""
        parent_id = request.query_params.get('parent')

        # Check if we're listing subtasks of a "CNC Kesim" task
        if parent_id:
            try:
                parent_task = JobOrderDepartmentTask.objects.get(id=parent_id)
                if parent_task.title == 'CNC Kesim':
                    # Return CNC parts instead of subtasks
                    from cnc_cutting.models import CncPart
                    from decimal import Decimal

                    cnc_parts = CncPart.objects.filter(
                        job_no=parent_task.job_order.job_no
                    ).select_related('cnc_task')

                    parts_data = []
                    for part in cnc_parts:
                        part_weight = (part.weight_kg or Decimal('0')) * (part.quantity or 1)
                        is_complete = part.cnc_task.completion_date is not None

                        # Map CNC part to department task structure
                        parts_data.append({
                            'id': f'cnc-part-{part.id}',
                            'type': 'cnc_part',
                            'cnc_part_id': part.id,
                            'job_order': part.cnc_task.nesting_id,
                            'job_order_title': parent_task.job_order.title,
                            'department': parent_task.department,
                            'department_display': parent_task.get_department_display(),
                            'title': f'{part.image_no} - Pos {part.position_no}' if part.position_no else part.image_no,
                            'status': 'completed' if is_complete else 'in_progress',
                            'status_display': 'Tamamlandı' if is_complete else 'Devam Ediyor',
                            'sequence': None,
                            'weight': float(part_weight),
                            'assigned_to': None,
                            'assigned_to_name': '',
                            'target_start_date': None,
                            'target_completion_date': None,
                            'started_at': None,
                            'completed_at': part.cnc_task.completion_date,
                            'parent': parent_task.id,
                            'subtasks_count': 0,
                            'can_start': False,
                            'created_at': None,
                            # CNC-specific fields
                            'cnc_data': {
                                'job_no': part.job_no,
                                'image_no': part.image_no,
                                'position_no': part.position_no,
                                'quantity': part.quantity,
                                'weight_kg': float(part.weight_kg) if part.weight_kg else None,
                                'total_weight': float(part_weight),
                                'cnc_task_key': part.cnc_task.key,
                            }
                        })

                    # Return in paginated format to match standard response structure
                    return Response({
                        'count': len(parts_data),
                        'next': None,
                        'previous': None,
                        'results': parts_data
                    })

                # Check if this is a "Talaşlı İmalat" task
                if parent_task.title == 'Talaşlı İmalat':
                    # Return machining Parts instead of subtasks
                    from tasks.models import Part, Operation
                    from django.db.models import Sum, Q, ExpressionWrapper, FloatField, Value
                    from django.db.models.functions import Coalesce
                    from decimal import Decimal

                    parts = Part.objects.filter(
                        job_no=parent_task.job_order.job_no
                    ).prefetch_related('operations')

                    parts_data = []
                    for part in parts:
                        # Get operations with annotated hours
                        operations = Operation.objects.filter(part=part).annotate(
                            total_hours_spent=Coalesce(
                                ExpressionWrapper(
                                    Sum('timers__finish_time', filter=Q(timers__finish_time__isnull=False)) -
                                    Sum('timers__start_time', filter=Q(timers__finish_time__isnull=False)),
                                    output_field=FloatField()
                                ) / 3600000.0,
                                Value(0.0)
                            )
                        )

                        # Calculate hours
                        estimated_hours = operations.aggregate(total=Sum('estimated_hours'))['total'] or Decimal('0.00')
                        hours_spent = sum(Decimal(str(op.total_hours_spent)) for op in operations)

                        # Calculate progress
                        if estimated_hours > 0:
                            progress_pct = min(float(hours_spent / estimated_hours * 100), 100.0)
                        else:
                            progress_pct = 0.0

                        # Map Part to department task structure
                        parts_data.append({
                            'id': f'machining-part-{part.key}',
                            'type': 'machining_part',
                            'part_key': part.key,
                            'job_order': part.key,
                            'job_order_title': parent_task.job_order.title,
                            'department': parent_task.department,
                            'department_display': parent_task.get_department_display(),
                            'title': f'{part.image_no} - Pos {part.position_no}' if part.position_no else part.name,
                            'status': 'completed' if progress_pct >= 100 else 'in_progress',
                            'status_display': 'Tamamlandı' if progress_pct >= 100 else 'Devam Ediyor',
                            'completion_percentage': progress_pct,
                            'sequence': None,
                            'weight': float(estimated_hours),
                            'assigned_to': None,
                            'assigned_to_name': '',
                            'target_start_date': None,
                            'target_completion_date': None,
                            'started_at': None,
                            'completed_at': part.completion_date,
                            'parent': parent_task.id,
                            'subtasks_count': 0,
                            'can_start': False,
                            'created_at': part.created_at,
                            # Machining-specific fields
                            'machining_data': {
                                'key': part.key,
                                'name': part.name,
                                'job_no': part.job_no,
                                'image_no': part.image_no,
                                'position_no': part.position_no,
                                'quantity': part.quantity,
                                'estimated_hours': float(estimated_hours),
                                'hours_spent': float(hours_spent),
                                'material': part.material,
                                'dimensions': part.dimensions,
                            }
                        })

                    # Return in paginated format to match standard response structure
                    return Response({
                        'count': len(parts_data),
                        'next': None,
                        'previous': None,
                        'results': parts_data
                    })

                # Check if this is a procurement task
                if parent_task.department == 'procurement':
                    # Return PlanningRequestItems instead of subtasks
                    from planning.models import PlanningRequestItem
                    from decimal import Decimal

                    items = PlanningRequestItem.objects.filter(
                        job_no=parent_task.job_order.job_no,
                        quantity_to_purchase__gt=0  # Only items that need procurement
                    ).select_related('item', 'planning_request')

                    items_data = []
                    for item in items:
                        # Calculate progress for this item
                        earned, total = item.get_procurement_progress() if hasattr(item, 'get_procurement_progress') else (Decimal('0.00'), item.total_weight if hasattr(item, 'total_weight') else Decimal('1.00'))

                        if total > 0:
                            progress_pct = float((earned / total * 100).quantize(Decimal('0.01')))
                        else:
                            progress_pct = 0.0

                        # Determine status based on progress
                        if progress_pct >= 100:
                            status = 'completed'
                            status_display = 'Ödendi'
                        elif progress_pct >= 50:
                            status = 'in_progress'
                            status_display = 'Onaylandı'
                        elif progress_pct >= 40:
                            status = 'in_progress'
                            status_display = 'Gönderildi'
                        else:
                            status = 'pending'
                            status_display = 'Bekliyor'

                        # Map PlanningRequestItem to department task structure
                        item_name = item.item.name if item.item else item.item_description
                        item_code = item.item.code if item.item else ''

                        items_data.append({
                            'id': f'procurement-item-{item.id}',
                            'type': 'procurement_item',
                            'procurement_item_id': item.id,
                            'job_order': item.job_no,
                            'job_order_title': parent_task.job_order.title,
                            'department': parent_task.department,
                            'department_display': parent_task.get_department_display(),
                            'title': f'{item_code} - {item_name}' if item_code else item_name,
                            'status': status,
                            'status_display': status_display,
                            'completion_percentage': progress_pct,
                            'sequence': None,
                            'weight': float(total),
                            'assigned_to': None,
                            'assigned_to_name': '',
                            'target_start_date': None,
                            'target_completion_date': None,
                            'started_at': None,
                            'completed_at': None,
                            'parent': parent_task.id,
                            'subtasks_count': 0,
                            'can_start': False,
                            'created_at': item.planning_request.created_at if item.planning_request else None,
                            # Procurement-specific fields
                            'procurement_data': {
                                'id': item.id,
                                'item_code': item_code,
                                'item_name': item_name,
                                'item_description': item.item_description,
                                'quantity': float(item.quantity),
                                'quantity_to_purchase': float(item.quantity_to_purchase),
                                'quantity_from_inventory': float(item.quantity_from_inventory),
                                'unit_weight': float(item.item.unit_weight) if item.item and hasattr(item.item, 'unit_weight') else 1.0,
                                'total_weight': float(total),
                                'earned_weight': float(earned),
                            }
                        })

                    # Return in paginated format to match standard response structure
                    return Response({
                        'count': len(items_data),
                        'next': None,
                        'previous': None,
                        'results': items_data
                    })

            except JobOrderDepartmentTask.DoesNotExist:
                pass

        # Default behavior for non-CNC/non-machining/non-procurement tasks
        return super().list(request, *args, **kwargs)

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

        # Update task statuses based on dependencies
        for task in created_tasks:
            task.update_status_from_dependencies()

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


# ============================================================================
# Discussion System ViewSets
# ============================================================================

class JobOrderDiscussionTopicViewSet(viewsets.ModelViewSet):
    """ViewSet for discussion topics."""

    queryset = JobOrderDiscussionTopic.objects.filter(
        is_deleted=False
    ).select_related('job_order', 'created_by').prefetch_related('mentioned_users', 'attachments')

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'content', 'job_order__job_no', 'job_order__title']
    ordering_fields = ['created_at', 'priority', 'updated_at']
    ordering = ['-created_at']
    filterset_fields = {
        'job_order': ['exact'],
        'priority': ['exact', 'in'],
        'created_by': ['exact'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return JobOrderDiscussionTopicListSerializer
        elif self.action == 'retrieve':
            return JobOrderDiscussionTopicDetailSerializer
        elif self.action == 'create':
            return JobOrderDiscussionTopicCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return JobOrderDiscussionTopicUpdateSerializer
        return JobOrderDiscussionTopicDetailSerializer

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsTopicOwnerOrReadOnly()]
        return [IsOfficeUser()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        topic = self.get_object()
        topic.is_deleted = True
        topic.deleted_at = timezone.now()
        topic.deleted_by = request.user
        topic.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        return Response({'status': 'success', 'message': 'Tartışma konusu silindi.'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def comments(self, request, pk=None):
        """Get all comments for this topic."""
        topic = self.get_object()
        comments = topic.comments.filter(is_deleted=False).select_related('created_by').prefetch_related('mentioned_users', 'attachments')
        serializer = JobOrderDiscussionCommentListSerializer(comments, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser])
    def upload_attachment(self, request, pk=None):
        """Upload file attachment to topic."""
        topic = self.get_object()
        file_obj = request.data.get('file')

        if not file_obj:
            return Response({'error': 'Dosya gerekli.'}, status=status.HTTP_400_BAD_REQUEST)

        attachment = DiscussionAttachment.objects.create(
            topic=topic,
            file=file_obj,
            uploaded_by=request.user
        )

        serializer = DiscussionAttachmentSerializer(attachment, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class JobOrderDiscussionCommentViewSet(viewsets.ModelViewSet):
    """ViewSet for discussion comments."""

    queryset = JobOrderDiscussionComment.objects.filter(
        is_deleted=False
    ).select_related('topic', 'topic__job_order', 'created_by').prefetch_related('mentioned_users', 'attachments')

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['content']
    ordering_fields = ['created_at']
    ordering = ['created_at']
    filterset_fields = {
        'topic': ['exact'],
        'created_by': ['exact'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return JobOrderDiscussionCommentListSerializer
        elif self.action == 'retrieve':
            return JobOrderDiscussionCommentDetailSerializer
        elif self.action == 'create':
            return JobOrderDiscussionCommentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return JobOrderDiscussionCommentUpdateSerializer
        return JobOrderDiscussionCommentDetailSerializer

    def get_permissions(self):
        if self.action in ['update', 'partial_update', 'destroy']:
            return [IsCommentAuthorOrReadOnly()]
        return [IsOfficeUser()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def destroy(self, request, *args, **kwargs):
        comment = self.get_object()
        comment.is_deleted = True
        comment.deleted_at = timezone.now()
        comment.deleted_by = request.user
        comment.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
        return Response({'status': 'success', 'message': 'Yorum silindi.'}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser])
    def upload_attachment(self, request, pk=None):
        """Upload file attachment to comment."""
        comment = self.get_object()
        file_obj = request.data.get('file')

        if not file_obj:
            return Response({'error': 'Dosya gerekli.'}, status=status.HTTP_400_BAD_REQUEST)

        attachment = DiscussionAttachment.objects.create(
            comment=comment,
            file=file_obj,
            uploaded_by=request.user
        )

        serializer = DiscussionAttachmentSerializer(attachment, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DiscussionNotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for notifications (read-only + mark as read)."""

    queryset = DiscussionNotification.objects.all()
    serializer_class = DiscussionNotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    filter_backends = [DjangoFilterBackend, OrderingFilter]
    ordering_fields = ['created_at']
    ordering = ['-created_at']
    filterset_fields = {
        'is_read': ['exact'],
        'notification_type': ['exact'],
    }

    def get_queryset(self):
        return DiscussionNotification.objects.filter(
            user=self.request.user
        ).select_related('topic', 'topic__job_order', 'comment')

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        serializer = self.get_serializer(notification)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        updated = DiscussionNotification.objects.filter(
            user=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'status': 'success', 'message': f'{updated} bildirim okundu olarak işaretlendi.'})

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = DiscussionNotification.objects.filter(user=request.user, is_read=False).count()
        return Response({'count': count})
