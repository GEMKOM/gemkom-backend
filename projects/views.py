from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db import transaction

from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES,
    JobOrderDiscussionTopic, JobOrderDiscussionComment,
    DiscussionAttachment,
    TechnicalDrawingRelease
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
    TechnicalDrawingReleaseListSerializer,
    TechnicalDrawingReleaseDetailSerializer,
    TechnicalDrawingReleaseCreateSerializer,
    RevisionRequestSerializer,
    ApproveRevisionSerializer,
    SelfRevisionSerializer,
    CompleteRevisionSerializer,
    RejectRevisionSerializer,
    BulkCreateSubtasksSerializer,
)
from .permissions import (
    IsOfficeUser, IsTopicOwnerOrReadOnly, IsCommentAuthorOrReadOnly,
    IsCostAuthorized, IsPlanning,
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
        from django.db.models import Count, Q, Subquery, OuterRef
        from .models import JobOrderTargetDateRevision
        latest_revision = JobOrderTargetDateRevision.objects.filter(
            job_order=OuterRef('pk')
        ).order_by('-changed_at')
        queryset = JobOrder.objects.select_related(
            'customer', 'parent', 'created_by', 'completed_by', 'source_offer'
        ).annotate(
            ncr_count=Count('ncrs', distinct=True),
            children_count=Count('children', distinct=True),
            revision_count=Count(
                'technical_drawing_releases',
                filter=Q(technical_drawing_releases__status='superseded'),
                distinct=True
            ),
            target_date_revisions_count=Count('target_date_revisions', distinct=True),
            previous_target_date_revision=Subquery(latest_revision.values('previous_date')[:1]),
        ).exclude(job_no='LEGACY-ARCHIVE')

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
        from projects.services.job_order import rename_job_no, cascade_customer_to_children

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        old_job_no = instance.job_no
        old_customer_id = instance.customer_id

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        new_job_no = serializer.validated_data.get('job_no', old_job_no)
        new_customer = serializer.validated_data.get('customer', None)

        # Rename job_no first (before saving other fields) so the PK is consistent.
        if new_job_no != old_job_no:
            rename_job_no(old_job_no, new_job_no)
            # The instance PK has changed; re-fetch so perform_update saves to the right row.
            instance = self.get_queryset().get(job_no=new_job_no)
            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)

        self.perform_update(serializer)

        # Cascade customer change to all child job orders.
        if new_customer and new_customer.pk != old_customer_id:
            cascade_customer_to_children(serializer.instance)

        detail_serializer = JobOrderDetailSerializer(serializer.instance)
        return Response(detail_serializer.data)

    def perform_update(self, serializer):
        reason = serializer.validated_data.pop('target_date_change_reason', '') or ''
        instance = serializer.instance
        instance._date_change_reason = reason
        instance._date_changed_by = self.request.user
        serializer.save()

    @action(detail=False, methods=['get'])
    def dropdown(self, request):
        """Lightweight list of job orders for dropdowns.
        ?all=true  → include all job orders regardless of status.
        (default)  → exclude completed and cancelled.
        """
        results = [{'job_no': '1000', 'title': 'Fabrika İşleri'}]
        qs = JobOrder.objects.order_by('job_no')
        if request.query_params.get('all') != 'true':
            qs = qs.exclude(status__in=['completed', 'cancelled'])
        results.extend(
            {'job_no': job_no, 'title': title}
            for job_no, title in qs.values_list('job_no', 'title')
        )
        return Response(results)

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
            from .signals import send_job_on_hold_notifications
            send_job_on_hold_notifications(job_order, reason)
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
            from .signals import send_job_resumed_notifications
            send_job_resumed_notifications(job_order)
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

    @action(detail=True, methods=['post'], url_path='recalculate_progress')
    def recalculate_progress(self, request, job_no=None):
        """Recalculate completion percentage for this job order from scratch."""
        job_order = self.get_object()
        old_pct = job_order.completion_percentage

        # Recalculate children first so parent aggregation is accurate
        for child in job_order.children.all():
            child.update_completion_percentage()

        job_order.update_completion_percentage()
        job_order.refresh_from_db()
        return Response({
            'job_no': job_order.job_no,
            'old_percentage': float(old_pct),
            'new_percentage': float(job_order.completion_percentage),
        })

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

    # -------------------------------------------------------------------------
    # Tab-specific endpoints (lightweight data loading)
    # -------------------------------------------------------------------------

    @action(detail=True, methods=['get'])
    def general(self, request, job_no=None):
        """
        Tab 1: General information only.
        Returns basic job order info without nested data.
        """
        job_order = self.get_object()
        data = {
            'job_no': job_order.job_no,
            'title': job_order.title,
            'description': job_order.description,
            'customer': job_order.customer_id,
            'customer_name': job_order.customer.name if job_order.customer else None,
            'customer_code': job_order.customer.code if job_order.customer else None,
            'customer_order_no': job_order.customer_order_no,
            'status': job_order.status,
            'status_display': job_order.get_status_display(),
            'priority': job_order.priority,
            'priority_display': job_order.get_priority_display(),
            'target_completion_date': job_order.target_completion_date,
            'started_at': job_order.started_at,
            'completed_at': job_order.completed_at,
            'estimated_cost': job_order.estimated_cost,
            'completion_percentage': job_order.completion_percentage,
            'parent': job_order.parent_id,
            'parent_title': job_order.parent.title if job_order.parent else None,
            'created_at': job_order.created_at,
            'created_by': job_order.created_by_id,
            'created_by_name': job_order.created_by.get_full_name() if job_order.created_by else None,
            'updated_at': job_order.updated_at,
        }
        return Response(data)

    @action(detail=True, methods=['get'])
    def department_tasks(self, request, job_no=None):
        """
        Tab 2: Department tasks with progress.
        Returns main tasks with their subtasks nested.
        """
        job_order = self.get_object()
        tasks = job_order.department_tasks.filter(
            parent__isnull=True
        ).select_related('assigned_to').prefetch_related('subtasks').order_by('sequence')

        from .serializers import JobOrderDepartmentTaskNestedSerializer
        return Response(JobOrderDepartmentTaskNestedSerializer(tasks, many=True).data)

    @action(detail=True, methods=['get'])
    def subtasks(self, request, job_no=None):
        """
        Tab 3: Child job orders (subtasks).
        Returns direct children of this job order.
        """
        job_order = self.get_object()
        children = job_order.children.select_related('customer').order_by('job_no')

        data = [{
            'job_no': child.job_no,
            'title': child.title,
            'status': child.status,
            'status_display': child.get_status_display(),
            'priority': child.priority,
            'priority_display': child.get_priority_display(),
            'completion_percentage': child.completion_percentage,
            'target_completion_date': child.target_completion_date,
            'children_count': child.children.count(),
        } for child in children]

        return Response(data)

    @action(detail=True, methods=['get'])
    def files(self, request, job_no=None):
        """
        Tab 4: Files/attachments.
        Returns all files for this job order.
        """
        job_order = self.get_object()
        files = job_order.files.select_related('uploaded_by').order_by('-uploaded_at')

        data = [{
            'id': f.id,
            'file_name': f.file_name,
            'file_type': f.file_type,
            'file_size': f.file_size,
            'file_url': f.file.url if f.file else None,
            'description': f.description,
            'uploaded_by': f.uploaded_by_id,
            'uploaded_by_name': f.uploaded_by.get_full_name() if f.uploaded_by else None,
            'uploaded_at': f.uploaded_at,
        } for f in files]

        return Response(data)

    @action(detail=True, methods=['get'])
    def topics(self, request, job_no=None):
        """
        Tab 5: Discussion topics.
        Returns all discussion topics for this job order.
        Only available for main job orders (parent IS NULL).
        """
        job_order = self.get_object()

        if job_order.parent is not None:
            return Response(
                {'error': 'Tartışma konuları sadece ana iş emirlerinde bulunur.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        topics = job_order.discussion_topics.filter(
            is_deleted=False
        ).select_related('created_by').prefetch_related('comments').order_by('-created_at')

        data = [{
            'id': topic.id,
            'title': topic.title,
            'content': topic.content,
            'priority': topic.priority,
            'priority_display': topic.get_priority_display(),
            'created_by': topic.created_by_id,
            'created_by_name': topic.created_by.get_full_name() if topic.created_by else None,
            'created_by_username': topic.created_by.username if topic.created_by else None,
            'created_at': topic.created_at,
            'is_edited': topic.is_edited,
            'edited_at': topic.edited_at,
            'comment_count': topic.get_comment_count(),
            'participant_count': topic.get_participant_count(),
        } for topic in topics]

        return Response(data)

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
        """Get all files for this job order (direct uploads + offer files)."""
        job_order = self.get_object()

        file_type = request.query_params.get('file_type')

        # Direct uploads
        direct_qs = job_order.files.select_related('uploaded_by')
        if file_type:
            direct_qs = direct_qs.filter(file_type=file_type)
        serializer = JobOrderFileSerializer(direct_qs, many=True, context={'request': request})
        direct_files = [{'source': 'job_order', **f} for f in serializer.data]

        # Offer files (from sales conversion)
        offer_qs = job_order.offer_files.select_related('uploaded_by', 'offer')
        if file_type:
            offer_qs = offer_qs.filter(file_type=file_type)
        offer_files = []
        for f in offer_qs:
            file_url = request.build_absolute_uri(f.file.url) if f.file else None
            offer_files.append({
                'source': 'sales_offer',
                'id': f.id,
                'offer_no': f.offer.offer_no,
                'file_url': file_url,
                'filename': f.file.name.split('/')[-1] if f.file else None,
                'file_size': f.file.size if f.file else None,
                'file_type': f.file_type,
                'file_type_display': f.get_file_type_display(),
                'name': f.name,
                'description': f.description,
                'uploaded_at': f.uploaded_at,
                'uploaded_by': f.uploaded_by_id,
                'uploaded_by_name': f.uploaded_by.get_full_name() if f.uploaded_by else '',
            })

        return Response({
            'job_order_files': direct_files,
            'offer_files': offer_files,
        })

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_file(self, request, job_no=None):
        """Upload one or more files to this job order.

        Send multiple files as repeated `files` fields (multipart).
        Shared metadata (file_type, name, description) applies to all files.
        """
        job_order = self.get_object()
        uploaded_files = request.FILES.getlist('files')

        if not uploaded_files:
            # Fallback: single-file field named 'file'
            single = request.FILES.get('file')
            if not single:
                return Response(
                    {'status': 'error', 'message': 'En az bir dosya gönderilmelidir.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            uploaded_files = [single]

        file_type = request.data.get('file_type', 'other')
        name = request.data.get('name', '')
        description = request.data.get('description', '')

        created = []
        errors = []

        for f in uploaded_files:
            serializer = JobOrderFileUploadSerializer(data={
                'file': f,
                'file_type': file_type,
                'name': name or f.name,
                'description': description,
            })
            if serializer.is_valid():
                file_obj = serializer.save(job_order=job_order, uploaded_by=request.user)
                created.append(JobOrderFileSerializer(file_obj, context={'request': request}).data)
            else:
                errors.append({'filename': f.name, 'errors': serializer.errors})

        if errors and not created:
            return Response({'status': 'error', 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'status': 'success',
            'message': f'{len(created)} dosya yüklendi.',
            'files': created,
            **(({'errors': errors}) if errors else {}),
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

    # -------------------------------------------------------------------------
    # Cost actions
    # -------------------------------------------------------------------------

    @staticmethod
    def _compute_aggregated_weights(parent_nos):
        """
        For each job_no in parent_nos, recursively sum total_weight_kg of all
        descendants and return a {job_no: Decimal} map.  Only entries with a
        non-zero total are included.
        """
        from decimal import Decimal
        if not parent_nos:
            return {}

        child_map = {}   # parent_no -> [child_nos]
        weight_map = {}  # child job_no -> own weight
        frontier = set(parent_nos)
        all_known = set(parent_nos)

        while frontier:
            rows = list(
                JobOrder.objects
                .filter(parent_id__in=frontier)
                .values_list('job_no', 'parent_id', 'total_weight_kg')
            )
            frontier = set()
            for jno, pid, weight in rows:
                weight_map[jno] = weight or Decimal(0)
                child_map.setdefault(pid, []).append(jno)
                if jno not in all_known:
                    frontier.add(jno)
                    all_known.add(jno)

        def subtree_weight(jno):
            return weight_map.get(jno, Decimal(0)) + sum(
                subtree_weight(c) for c in child_map.get(jno, [])
            )

        return {jno: val for jno in parent_nos if (val := subtree_weight(jno))}

    @staticmethod
    def _serialize_cost_rows(jobs, jobs_with_children, context):
        """
        Serialize a list of JobOrder instances with CostTableRowSerializer and
        inject the has_children flag from the provided set.
        """
        from .serializers import CostTableRowSerializer
        serializer = CostTableRowSerializer(jobs, many=True, context=context)
        return [
            {**item, 'has_children': item['job_no'] in jobs_with_children}
            for item in serializer.data
        ]

    @action(detail=False, methods=['get'], url_path='cost_table', permission_classes=[IsCostAuthorized])
    def cost_table(self, request):
        """
        Returns paginated root-level job orders with cost breakdown.

        Each row includes has_children=true/false. When true, call
        GET /projects/job-orders/{job_no}/cost_children/ to load that job's
        direct children on demand.

        'count' in the pagination envelope is the total number of roots.
        Filters promote jobs to roots when their parent is excluded.
        """
        from django.db.models import ExpressionWrapper, DecimalField, F, Value
        from django.db.models.functions import NullIf
        from django.db.models import OrderBy

        ordering_param = request.query_params.get('ordering', 'job_no')

        # Expressions for computed ordering fields
        margin_eur_expr = ExpressionWrapper(
            F('cost_summary__selling_price') - F('cost_summary__actual_total_cost'),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
        margin_pct_expr = ExpressionWrapper(
            (F('cost_summary__selling_price') - F('cost_summary__actual_total_cost'))
            / NullIf(F('cost_summary__selling_price'), Value(0)) * Value(100),
            output_field=DecimalField(max_digits=10, decimal_places=4),
        )
        price_per_kg_expr = ExpressionWrapper(
            F('cost_summary__actual_total_cost')
            / NullIf(F('total_weight_kg'), Value(0)),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )

        db_ordering = {
            'job_no':          ('job_no',),
            '-job_no':         ('-job_no',),
            'title':           ('title',),
            '-title':          ('-title',),
            'weight':          ('total_weight_kg',),
            '-weight':         ('-total_weight_kg',),
            'actual_cost':     ('cost_summary__actual_total_cost',),
            '-actual_cost':    ('-cost_summary__actual_total_cost',),
            'selling_price':   ('cost_summary__selling_price',),
            '-selling_price':  ('-cost_summary__selling_price',),
            'completion_pct':  ('completion_percentage',),
            '-completion_pct': ('-completion_percentage',),
            'date':            (OrderBy(F('target_completion_date'), nulls_last=True),),
            '-date':           (OrderBy(F('target_completion_date'), descending=True, nulls_last=True),),
            'created_at':      ('created_at',),
            '-created_at':     ('-created_at',),
            'last_updated':    ('cost_summary__last_updated',),
            '-last_updated':   ('-cost_summary__last_updated',),
            # Computed via annotated expressions (applied below)
            'margin_eur':      None,
            '-margin_eur':     None,
            'margin_pct':      None,
            '-margin_pct':     None,
            'price_per_kg':    None,
            '-price_per_kg':   None,
        }

        annotation_ordering = {
            'margin_eur':   ('margin_eur_order',  margin_eur_expr,  False),
            '-margin_eur':  ('margin_eur_order',  margin_eur_expr,  True),
            'margin_pct':   ('margin_pct_order',  margin_pct_expr,  False),
            '-margin_pct':  ('margin_pct_order',  margin_pct_expr,  True),
            'price_per_kg': ('price_per_kg_order', price_per_kg_expr, False),
            '-price_per_kg':('price_per_kg_order', price_per_kg_expr, True),
        }

        base_qs = (
            JobOrder.objects
            .select_related('cost_summary', 'customer', 'source_offer')
            .prefetch_related('source_offer__price_revisions')
            .exclude(job_no='LEGACY-ARCHIVE')
            .exclude(cost_summary__cost_not_applicable=True)
        )

        facility = request.query_params.get('facility')
        if facility == 'rolling_mill':
            base_qs = base_qs.filter(job_no__istartswith='RM')
        elif facility == 'meltshop':
            base_qs = base_qs.exclude(job_no__istartswith='RM')

        if ordering_param in annotation_ordering:
            ann_name, ann_expr, descending = annotation_ordering[ordering_param]
            base_qs = base_qs.annotate(**{ann_name: ann_expr})
            db_order = f'-{ann_name}' if descending else ann_name
        else:
            db_order = db_ordering.get(ordering_param, ('job_no',))[0]

        base_qs = base_qs.order_by(db_order)
        filtered_qs = self.filter_queryset(base_qs)

        # One lightweight query to learn the full parent/child structure.
        # Use values_list to get an ordered list of (job_no, parent_id) pairs;
        # the queryset already has order_by applied so DB returns them sorted.
        job_meta = list(filtered_qs.values_list('job_no', 'parent_id'))
        job_no_set = {m[0] for m in job_meta}
        jobs_with_children = {m[1] for m in job_meta if m[1] in job_no_set}
        root_nos = [
            m[0] for m in job_meta
            if not m[1] or m[1] not in job_no_set
        ]

        # Paginate the root list (DRF paginators accept Python lists).
        page = self.paginate_queryset(root_nos)
        root_page_nos = page if page is not None else root_nos

        root_jobs = list(filtered_qs.filter(job_no__in=root_page_nos)) if root_page_nos else []
        # Restore the paginated order (filter(in=) doesn't guarantee it).
        order_map = {no: i for i, no in enumerate(root_page_nos)}
        root_jobs.sort(key=lambda j: order_map[j.job_no])

        parent_root_nos = {j.job_no for j in root_jobs if j.job_no in jobs_with_children}
        aggregated_weights = self._compute_aggregated_weights(parent_root_nos)
        ctx = {**self.get_serializer_context(), 'aggregated_weights': aggregated_weights}
        data = self._serialize_cost_rows(root_jobs, jobs_with_children, ctx)

        if page is not None:
            return self.get_paginated_response(data)
        return Response(data)

    @action(detail=True, methods=['get'], url_path='cost_children', permission_classes=[IsCostAuthorized])
    def cost_children(self, request, job_no=None):
        """
        Returns direct children of the given job order with cost breakdown.
        Each row includes has_children so the frontend knows whether to show
        a further expand button.
        """
        children = list(
            JobOrder.objects
            .select_related('cost_summary', 'customer', 'source_offer')
            .prefetch_related('source_offer__price_revisions')
            .filter(parent_id=job_no)
            .order_by('job_no')
        )
        child_nos = {c.job_no for c in children}
        # Determine which children themselves have children.
        grandchild_parent_nos = set(
            JobOrder.objects
            .filter(parent_id__in=child_nos)
            .values_list('parent_id', flat=True)
            .distinct()
        )
        aggregated_weights = self._compute_aggregated_weights(grandchild_parent_nos)
        ctx = {**self.get_serializer_context(), 'aggregated_weights': aggregated_weights}
        data = self._serialize_cost_rows(children, grandchild_parent_nos, ctx)
        return Response(data)

    @action(detail=True, methods=['get', 'patch'], url_path='cost_summary', permission_classes=[IsCostAuthorized])
    def cost_summary(self, request, job_no=None):
        """
        GET  → return cost summary for this job order (creates empty one if none exists).
        PATCH → update selling_price / selling_price_currency.
        """
        from .serializers import JobOrderCostSummarySerializer
        from .models import JobOrderCostSummary

        job_order = self.get_object()

        if request.method == 'GET':
            summary, _ = JobOrderCostSummary.objects.get_or_create(
                job_order=job_order
            )
            summary.job_order = job_order  # avoids extra query for general_expenses_rate
            return Response(JobOrderCostSummarySerializer(summary).data)

        # PATCH
        summary, _ = JobOrderCostSummary.objects.get_or_create(
            job_order=job_order
        )

        # Only planning team (or superusers) may set cost_not_applicable
        if 'cost_not_applicable' in request.data and not IsPlanning().has_permission(request, self):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only planning team members can mark a job order as cost not applicable.")

        serializer = JobOrderCostSummarySerializer(
            summary, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Recompute if any rate that affects computed costs was patched
        rate_fields = {'paint_material_rate', 'employee_overhead_rate'}
        if rate_fields & set(request.data.keys()):
            from projects.services.costing import recompute_job_cost_summary
            recompute_job_cost_summary(job_order.job_no)
            summary.refresh_from_db()
            summary.job_order = job_order

        return Response(JobOrderCostSummarySerializer(summary).data)

    @action(detail=True, methods=['get'], url_path='subcontractor_cost_breakdown', permission_classes=[IsCostAuthorized])
    def subcontractor_cost_breakdown(self, request, job_no=None):
        """
        Returns the subcontractor cost breakdown for this job order and its children.
        Includes approved/paid statement lines and adjustments, each converted to EUR.
        """
        from subcontracting.models import SubcontractorStatementLine, SubcontractorStatementAdjustment
        from projects.services.costing import convert_to_eur
        from django.db.models import Q
        from decimal import Decimal

        job_order = self.get_object()
        prefix = f'{job_order.job_no}-'
        approved_statuses = ['approved', 'paid']

        lines = (
            SubcontractorStatementLine.objects
            .filter(
                Q(job_no=job_order.job_no) | Q(job_no__startswith=prefix),
                statement__status__in=approved_statuses,
            )
            .exclude(assignment__department_task__task_type='painting')
            .select_related('statement', 'assignment__department_task')
            .order_by('statement__year', 'statement__month', 'job_no', 'id')
        )

        adjustments = (
            SubcontractorStatementAdjustment.objects
            .filter(
                Q(job_order__job_no=job_order.job_no) | Q(job_order__job_no__startswith=prefix),
                statement__status__in=approved_statuses,
            )
            .select_related('statement', 'job_order')
            .order_by('statement__year', 'statement__month', 'id')
        )

        line_data = [
            {
                'type': 'work',
                'statement_year': line.statement.year,
                'statement_month': line.statement.month,
                'statement_status': line.statement.status,
                'job_no': line.job_no,
                'job_title': line.job_title,
                'subcontractor_name': line.subcontractor_name,
                'price_tier_name': line.price_tier_name,
                'allocated_weight_kg': str(line.allocated_weight_kg),
                'previous_progress': str(line.previous_progress),
                'current_progress': str(line.current_progress),
                'delta_progress': str(line.delta_progress),
                'effective_weight_kg': str(line.effective_weight_kg),
                'price_per_kg': str(line.price_per_kg),
                'cost_amount': str(line.cost_amount),
                'cost_currency': line.statement.currency,
                'cost_amount_eur': str(
                    convert_to_eur(line.cost_amount, line.statement.currency, line.statement.approved_at.date())
                    .quantize(Decimal('0.01'))
                ),
            }
            for line in lines
        ]

        adj_data = [
            {
                'type': 'adjustment',
                'statement_year': adj.statement.year,
                'statement_month': adj.statement.month,
                'statement_status': adj.statement.status,
                'job_no': adj.job_order.job_no,
                'adjustment_type': adj.adjustment_type,
                'reason': adj.reason,
                'description': adj.description,
                'amount': str(adj.amount),
                'cost_currency': adj.statement.currency,
                'cost_amount_eur': str(
                    convert_to_eur(adj.amount, adj.statement.currency, adj.statement.approved_at.date())
                    .quantize(Decimal('0.01'))
                ),
            }
            for adj in adjustments
        ]

        total_eur = sum((Decimal(r['cost_amount_eur']) for r in line_data + adj_data), Decimal('0'))

        return Response({
            'job_no': job_order.job_no,
            'total_eur': str(total_eur.quantize(Decimal('0.01'))),
            'lines': line_data,
            'adjustments': adj_data,
        })

    @action(detail=False, methods=['get'], url_path='procurement_pending')
    def procurement_pending(self, request):
        """
        Returns job orders that have no saved procurement cost lines yet.
        Excludes only cancelled jobs. Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(procurement_line_count=Count('procurement_lines'))
            .filter(procurement_line_count=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
            .exclude(status='cancelled')
            .exclude(cost_summary__cost_not_applicable=True)
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='qc_pending')
    def qc_pending(self, request):
        """
        Returns job orders that have no QC cost lines yet.
        Excludes only cancelled jobs. Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(qc_line_count=Count('qc_cost_lines'))
            .filter(qc_line_count=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
            .exclude(status='cancelled')
            .exclude(cost_summary__cost_not_applicable=True)
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='shipping_pending')
    def shipping_pending(self, request):
        """
        Returns job orders that have no shipping cost lines yet.
        Excludes only cancelled jobs. Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(shipping_line_count=Count('shipping_cost_lines'))
            .filter(shipping_line_count=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
            .exclude(status='cancelled')
            .exclude(cost_summary__cost_not_applicable=True)
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='has_procurement')
    def has_procurement(self, request):
        """
        Returns job orders that have at least one saved procurement cost line.
        Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(procurement_line_count=Count('procurement_lines'))
            .filter(procurement_line_count__gt=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='has_qc')
    def has_qc(self, request):
        """
        Returns job orders that have at least one QC cost line.
        Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(qc_line_count=Count('qc_cost_lines'))
            .filter(qc_line_count__gt=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='has_shipping')
    def has_shipping(self, request):
        """
        Returns job orders that have at least one shipping cost line.
        Supports the same filters as the list view.
        """
        from django.db.models import Count

        qs = (
            JobOrder.objects
            .select_related('customer')
            .annotate(shipping_line_count=Count('shipping_cost_lines'))
            .filter(shipping_line_count__gt=0, children__isnull=True)
            .exclude(job_no='LEGACY-ARCHIVE')
        )
        qs = self.filter_queryset(qs)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = JobOrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = JobOrderListSerializer(qs, many=True)
        return Response(serializer.data)


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


def _bulk_create_subtask_tree(parent_task, tasks_data, user):
    """
    Inserts a nested subtask tree under parent_task using bulk_create per level.
    One DB round-trip per depth level (not per task).
    Returns a flat list of all created JobOrderDepartmentTask instances (with PKs).
    """
    job_order = parent_task.job_order
    department = parent_task.department
    all_created = []

    def process_level(items_data, parent_obj):
        if not items_data:
            return
        instances = []
        children_per_instance = []
        for item in items_data:
            children_per_instance.append(item.get('subtasks', []))
            instances.append(JobOrderDepartmentTask(
                job_order=job_order,
                department=department,
                parent=parent_obj,
                title=item['title'],
                weight=item.get('weight', 10),
                sequence=item.get('sequence', 1),
                task_type=item.get('task_type') or None,
                description=item.get('description') or None,
                notes=item.get('notes') or None,
                assigned_to=item.get('assigned_to'),
                target_start_date=item.get('target_start_date'),
                target_completion_date=item.get('target_completion_date'),
                status='pending',
                created_by=user,
            ))
        created = JobOrderDepartmentTask.objects.bulk_create(instances)
        all_created.extend(created)
        for created_instance, children in zip(created, children_per_instance):
            process_level(children, created_instance)

    with transaction.atomic():
        process_level(tasks_data, parent_task)
        for task in all_created:
            task.update_status_from_dependencies()
        job_order.update_completion_percentage()

    return all_created


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
    - POST /department-tasks/{id}/unskip/ - Revert a skipped task back to pending
    - POST /department-tasks/{id}/uncomplete/ - Revert completed task to in_progress
    """
    queryset = JobOrderDepartmentTask.objects.select_related(
        'job_order', 'job_order__customer', 'sales_offer', 'sales_offer__customer',
        'assigned_to', 'parent', 'created_by', 'completed_by'
    ).prefetch_related('subtasks', 'depends_on', 'qc_reviews', 'qc_reviews__ncr')
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'job_order__job_no', 'job_order__title']
    ordering_fields = ['sequence', 'status', 'created_at', 'target_completion_date', 'job_order', 'job_order__created_at', 'job_order__job_no']
    ordering = ['job_order__created_at', 'sequence']
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

        # Filter to design tasks that have a pending revision request
        has_pending_revision = self.request.query_params.get('has_pending_revision', '').lower() == 'true'
        if has_pending_revision:
            queryset = queryset.filter(
                department='design',
                parent__isnull=True,
                job_order__technical_drawing_releases__revision_topics__topic_type='revision_request',
                job_order__technical_drawing_releases__revision_topics__revision_status='pending',
                job_order__technical_drawing_releases__revision_topics__is_deleted=False,
            ).distinct()

        # Annotate consultation flag for ordering (applied after filter_queryset)
        from django.db.models import Case, When, Value, IntegerField
        queryset = queryset.annotate(
            _is_consultation=Case(
                When(sales_offer__isnull=False, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )

        return queryset

    def filter_queryset(self, queryset):
        # Let DRF apply filters + ordering first
        queryset = super().filter_queryset(queryset)
        # Only prepend consultation sort when no explicit ordering is requested
        if not self.request.query_params.get('ordering'):
            return queryset.order_by('_is_consultation', 'job_order__job_no')
        return queryset

    def list(self, request, *args, **kwargs):
        """Override list to return CNC parts for 'CNC Kesim' parent tasks."""
        parent_id = request.query_params.get('parent')

        # Check if we're listing subtasks of a "CNC Kesim" task
        if parent_id:
            try:
                parent_task = JobOrderDepartmentTask.objects.get(id=parent_id)
                # Check both task_type and title for CNC tasks
                is_cnc_task = parent_task.task_type == 'cnc_cutting' or parent_task.title == 'CNC Kesim'
                if is_cnc_task:
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
                # Check both task_type and title for machining tasks
                is_machining_task = parent_task.task_type == 'machining' or parent_task.title == 'Talaşlı İmalat'
                if is_machining_task:
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
                        is_part_completed = part.completion_date is not None
                        if is_part_completed:
                            progress_pct = 100.0
                        elif estimated_hours > 0:
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
                            'status': 'completed' if is_part_completed else 'in_progress',
                            'status_display': 'Tamamlandı' if is_part_completed else 'Devam Ediyor',
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
                        quantity_to_purchase__gt=0
                    ).select_related('item', 'planning_request').prefetch_related(
                        'purchase_request_items__purchase_request',
                        'purchase_request_items__po_lines__po',
                    )

                    items_data = []
                    for item in items:
                        earned, total = item.get_procurement_progress()

                        if total > 0:
                            progress_pct = float((earned / total * 100).quantize(Decimal('0.01')))
                        else:
                            progress_pct = 0.0

                        # Find linked purchase request and purchase order
                        purchase_request_number = None
                        purchase_order_id = None
                        po_line_id = None

                        pri_items = item.purchase_request_items.all()
                        for pri in pri_items:
                            pr = pri.purchase_request
                            if pr.status not in ('cancelled', 'rejected'):
                                purchase_request_number = pr.request_number
                                po_lines = pri.po_lines.all()
                                for po_line in po_lines:
                                    purchase_order_id = po_line.po_id
                                    po_line_id = po_line.id
                                break

                        # Determine status based on progress
                        if item.is_delivered:
                            status = 'completed'
                            status_display = 'Teslim Edildi'
                        elif progress_pct >= 80:
                            status = 'in_progress'
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

                        item_name = item.item.name if item.item else item.item_description
                        item_code = item.item.code if item.item else ''

                        items_data.append({
                            'id': f'procurement-item-{item.id}',
                            'planning_request_item_id': item.id,
                            'task_type': 'procurement_item',
                            'title': f'{item_code} - {item_name}' if item_code else item_name,
                            'planning_request_number': item.planning_request.request_number if item.planning_request else None,
                            'quantity_to_purchase': float(item.quantity_to_purchase),
                            'purchase_request_number': purchase_request_number,
                            'purchase_order_id': purchase_order_id,
                            'po_line_id': po_line_id,
                            'status': status,
                            'status_display': status_display,
                            'completion_percentage': progress_pct,
                            'is_delivered': item.is_delivered,
                        })

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
        prev_assigned_to_id = instance.assigned_to_id
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        task = serializer.instance
        new_assigned_to_id = task.assigned_to_id
        if new_assigned_to_id and new_assigned_to_id != prev_assigned_to_id:
            self._notify_task_assigned(request, task)
        detail_serializer = DepartmentTaskDetailSerializer(task)
        return Response(detail_serializer.data)

    def _notify_task_assigned(self, request, task):
        try:
            from notifications.service import notify, render_notification
            from notifications.models import Notification
            offer_no = task.sales_offer.offer_no if task.sales_offer_id else (task.job_order.job_no if task.job_order_id else '')
            ctx = {
                'actor': request.user.get_full_name(),
                'task_title': task.title,
                'task_id': task.id,
                'offer_no': offer_no,
                'department': task.department,
            }
            title, body, link = render_notification(Notification.TASK_ASSIGNED, ctx)
            notify(
                user=task.assigned_to,
                notification_type=Notification.TASK_ASSIGNED,
                title=title,
                body=body,
                link=link,
                source_type='department_task',
                source_id=task.id,
            )
        except Exception:
            pass

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
        """Complete the department task, optionally saving a notes/response comment."""
        task = self.get_object()
        notes = request.data.get('notes', None)
        try:
            task.complete(user=request.user, notes=notes)
            if task.task_type == 'sales_consult' and task.sales_offer_id:
                self._notify_sales_consult_completed(task, request.user)
            return Response({
                'status': 'success',
                'message': 'Görev tamamlandı.',
                'task': DepartmentTaskDetailSerializer(task, context={'request': request}).data
            })
        except ValueError as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _notify_sales_consult_completed(self, task, completed_by_user):
        try:
            from notifications.service import notify, render_notification
            from notifications.models import Notification
            offer = task.sales_offer
            if not offer.created_by_id:
                return
            ctx = {
                'offer_no':     offer.offer_no,
                'offer_title':  offer.title,
                'customer':     offer.customer.name,
                'department':   task.get_department_display(),
                'task_title':   task.title,
                'completed_by': completed_by_user.get_full_name() or completed_by_user.username,
            }
            title, body, link = render_notification(Notification.SALES_CONSULT_COMPLETED, ctx)
            notify(
                user=offer.created_by,
                notification_type=Notification.SALES_CONSULT_COMPLETED,
                title=title,
                body=body,
                link=link,
                source_type='sales_offer',
                source_id=offer.id,
            )
        except Exception:
            pass

    @action(detail=True, methods=['post'], url_path='upload-file',
            parser_classes=[MultiPartParser, FormParser])
    def upload_file(self, request, pk=None):
        """Upload a completion file to a department task."""
        from .serializers import DepartmentTaskFileUploadSerializer, DepartmentTaskFileSerializer
        task = self.get_object()
        serializer = DepartmentTaskFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file_obj = serializer.save(task=task, uploaded_by=request.user)
        return Response(
            DepartmentTaskFileSerializer(file_obj, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path=r'files/(?P<file_pk>\d+)')
    def delete_file(self, request, pk=None, file_pk=None):
        """Delete a completion file from a department task."""
        task = self.get_object()
        try:
            file_obj = task.completion_files.get(pk=file_pk)
        except task.completion_files.model.DoesNotExist:
            return Response({'detail': 'Dosya bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)
        file_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
    def unskip(self, request, pk=None):
        """Revert a skipped task back to pending."""
        task = self.get_object()
        try:
            task.unskip()
            return Response({
                'status': 'success',
                'message': 'Görev atlama durumu geri alındı.',
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

    @action(detail=True, methods=['post'], url_path='bulk_create_subtasks')
    def bulk_create_subtasks(self, request, pk=None):
        """
        Bulk-create a nested tree of subtasks under the given parent task.

        URL: POST /api/projects/department-tasks/{pk}/bulk_create_subtasks/

        Input:
        {
            "tasks": [
                {
                    "title": "Frame Welding",
                    "weight": 30,
                    "sequence": 1,
                    "subtasks": [
                        {"title": "Tack Weld", "weight": 10, "sequence": 1},
                        {"title": "Final Weld", "weight": 20, "sequence": 2}
                    ]
                }
            ]
        }

        - Department is inherited from the parent task.
        - depends_on is not supported in this endpoint.
        - Returns a flat list of all created tasks at all depth levels.
        """
        parent_task = self.get_object()

        if parent_task.status in ('completed', 'cancelled', 'skipped'):
            return Response(
                {'status': 'error', 'message': 'Tamamlanmış, iptal edilmiş veya atlanan görevlere alt görev eklenemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = BulkCreateSubtasksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created_tasks = _bulk_create_subtask_tree(
            parent_task=parent_task,
            tasks_data=serializer.validated_data['tasks'],
            user=request.user,
        )

        return Response(
            {
                'status': 'success',
                'message': f'{len(created_tasks)} alt görev oluşturuldu.',
                'tasks': DepartmentTaskListSerializer(created_tasks, many=True).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def destroy(self, request, *args, **kwargs):
        task = self.get_object()

        # Block deletion of main tasks (no parent)
        if task.parent_id is None:
            return Response(
                {'status': 'error', 'message': 'Ana görevler silinemez.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Block if there are regular subtasks
        if task.subtasks.exists():
            return Response(
                {'status': 'error', 'message': 'Alt görevleri olan bir görev silinemez. Önce alt görevleri silin.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Block if this is a 'CNC Kesim' task that has CNC parts
        # Check both task_type and title for CNC tasks
        is_cnc_task = task.task_type == 'cnc_cutting' or task.title == 'CNC Kesim'
        if is_cnc_task:
            from cnc_cutting.models import CncPart
            if CncPart.objects.filter(job_no=task.job_order.job_no).exists():
                return Response(
                    {'status': 'error', 'message': 'CNC parçaları olan bir görev silinemez. Önce CNC parçalarını silin.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Block if this is a 'Talaşlı İmalat' task that has machining parts
        # Check both task_type and title for machining tasks
        is_machining_task = task.task_type == 'machining' or task.title == 'Talaşlı İmalat'
        if is_machining_task:
            from tasks.models import Part
            if Part.objects.filter(job_no=task.job_order.job_no).exists():
                return Response(
                    {'status': 'error', 'message': 'Talaşlı imalat parçaları olan bir görev silinemez. Önce parçaları silin.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Block if the task has a subcontracting assignment with statement lines.
        # Django would raise ProtectedError on delete anyway, but we return a clean message.
        try:
            assignment = task.subcontracting_assignment
            if assignment.statement_lines.exists():
                return Response(
                    {'status': 'error', 'message': 'Bu göreve ait taşeron hakediş kalemleri bulunmaktadır. Görev silinemez.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception:
            pass  # No assignment — nothing to check

        job_order = task.job_order
        task.delete()
        job_order.update_completion_percentage()
        return Response(status=status.HTTP_204_NO_CONTENT)

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

    @action(detail=True, methods=['get'])
    def discussion(self, request, pk=None):
        """Return the discussion topic for this task, or null if none exists."""
        task = self.get_object()
        topic = task.discussion_topic.filter(is_deleted=False).first()
        if topic is None:
            return Response(None)
        serializer = JobOrderDiscussionTopicDetailSerializer(topic, context={'request': request})
        return Response(serializer.data)


# ============================================================================
# Discussion System ViewSets
# ============================================================================

class JobOrderDiscussionTopicViewSet(viewsets.ModelViewSet):
    """ViewSet for discussion topics."""

    queryset = JobOrderDiscussionTopic.objects.filter(
        is_deleted=False
    ).select_related('job_order', 'task', 'created_by').prefetch_related('mentioned_users', 'attachments')

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'content', 'job_order__job_no', 'job_order__title']
    ordering_fields = ['created_at', 'priority', 'updated_at']
    ordering = ['-created_at']
    filterset_fields = {
        'job_order': ['exact'],
        'job_order__job_no': ['exact'],
        'task': ['exact'],
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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        topic = serializer.save(created_by=request.user)
        # Return detail serializer with full topic data including id
        detail_serializer = JobOrderDiscussionTopicDetailSerializer(topic, context={'request': request})
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

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

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(created_by=request.user)
        # Return detail serializer with full comment data including id
        detail_serializer = JobOrderDiscussionCommentDetailSerializer(comment, context={'request': request})
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

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


# ============================================================================
# Technical Drawing Release ViewSet
# ============================================================================

class TechnicalDrawingReleaseViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Technical Drawing Release management with revision workflow.

    Standard CRUD:
    - GET    /drawing-releases/                        - List all releases
    - POST   /drawing-releases/                        - Create new release
    - GET    /drawing-releases/{id}/                   - Get release details
    - GET    /drawing-releases/?job_order={job_no}     - Filter by job order

    Revision Workflow Actions:
    - POST   /drawing-releases/{id}/request_revision/  - Request revision (pending)
    - POST   /drawing-releases/{id}/approve_revision/  - Approve request (triggers hold)
    - POST   /drawing-releases/{id}/self_revision/     - Self-initiate revision (immediate hold)
    - POST   /drawing-releases/{id}/complete_revision/ - Complete revision (triggers resume)
    - POST   /drawing-releases/{id}/reject_revision/   - Reject revision request
    """

    queryset = TechnicalDrawingRelease.objects.select_related(
        'job_order', 'released_by', 'release_topic'
    ).prefetch_related('revision_topics')

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['job_order__job_no', 'job_order__title', 'changelog', 'revision_code']
    ordering_fields = ['released_at', 'revision_number', 'created_at']
    ordering = ['-released_at']
    filterset_fields = {
        'job_order': ['exact'],
        'status': ['exact', 'in'],
        'released_by': ['exact'],
    }

    def get_serializer_class(self):
        if self.action == 'list':
            return TechnicalDrawingReleaseListSerializer
        elif self.action == 'retrieve':
            return TechnicalDrawingReleaseDetailSerializer
        elif self.action == 'create':
            return TechnicalDrawingReleaseCreateSerializer
        return TechnicalDrawingReleaseDetailSerializer

    def get_permissions(self):
        return [IsOfficeUser()]

    def perform_create(self, serializer):
        serializer.save(released_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        detail_serializer = TechnicalDrawingReleaseDetailSerializer(
            serializer.instance, context={'request': request}
        )
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    # -------------------------------------------------------------------------
    # Revision Workflow Actions
    # -------------------------------------------------------------------------

    @action(detail=True, methods=['post'])
    def request_revision(self, request, pk=None):
        """
        Request a revision for this release.
        Creates a pending revision request topic - NO job order hold yet.
        """
        release = self.get_object()

        # Validate release status
        if release.status != 'released':
            return Response(
                {'status': 'error', 'message': 'Sadece yayınlanmış çizimler için revizyon talep edilebilir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for existing pending revision request
        existing_pending = release.revision_topics.filter(
            revision_status='pending',
            is_deleted=False
        ).exists()
        if existing_pending:
            return Response(
                {'status': 'error', 'message': 'Bu yayın için zaten bekleyen bir revizyon talebi var.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = RevisionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data['reason']

        # Create revision request topic (pending - no hold yet)
        topic = JobOrderDiscussionTopic.objects.create(
            job_order=release.job_order,
            title=f"Revizyon Talebi - Rev.{release.revision_code or release.revision_number}",
            content=reason,
            priority='high',
            topic_type='revision_request',
            revision_status='pending',
            related_release=release,
            created_by=request.user
        )

        # Extract and set mentions
        mentioned_users = topic.extract_mentions()
        if mentioned_users.exists():
            topic.mentioned_users.set(mentioned_users)

        # Send notifications to design task assignee
        from .signals import send_revision_requested_notifications
        send_revision_requested_notifications(release, topic, request.user)

        return Response({
            'status': 'success',
            'message': 'Revizyon talebi oluşturuldu. Tasarım ekibinin onayı bekleniyor.',
            'topic': JobOrderDiscussionTopicDetailSerializer(topic, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve_revision(self, request, pk=None):
        """
        Approve a pending revision request.
        NOW triggers job order hold and uncompletes design task.
        """
        release = self.get_object()

        # Validate release status
        if release.status != 'released':
            return Response(
                {'status': 'error', 'message': 'Sadece yayınlanmış çizimler için revizyon onaylanabilir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ApproveRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        topic_id = serializer.validated_data['topic_id']
        assigned_to_id = serializer.validated_data.get('assigned_to')

        # Get the pending revision topic
        try:
            topic = release.revision_topics.get(
                id=topic_id,
                revision_status='pending',
                is_deleted=False
            )
        except JobOrderDiscussionTopic.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Bekleyen revizyon talebi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update release status
        release.status = 'in_revision'
        release.save(update_fields=['status', 'updated_at'])

        # Update topic status
        topic.revision_status = 'in_progress'
        if assigned_to_id:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                topic.revision_assigned_to = User.objects.get(id=assigned_to_id)
            except User.DoesNotExist:
                pass
        topic.save(update_fields=['revision_status', 'revision_assigned_to', 'updated_at'])

        # Add approval comment to the revision topic
        assigned_name = topic.revision_assigned_to.get_full_name() if topic.revision_assigned_to else None
        comment_text = f"**Revizyon talebi onaylandı.** Çizim incelemeye alındı."
        if assigned_name:
            comment_text += f" Revizyon {assigned_name} tarafından gerçekleştirilecek."
        JobOrderDiscussionComment.objects.create(
            topic=topic,
            content=comment_text,
            created_by=request.user
        )

        # Put job order on hold
        job_order = release.job_order
        job_order.hold(reason=f"Revizyon: {topic.title}")

        # Uncomplete design department task
        design_task = job_order.department_tasks.filter(
            department='design',
            parent__isnull=True
        ).first()
        if design_task and design_task.status == 'completed':
            design_task.uncomplete()

        # Send notifications
        from .signals import send_revision_approved_notifications
        send_revision_approved_notifications(release, topic, request.user)

        return Response({
            'status': 'success',
            'message': 'Revizyon onaylandı. İş emri beklemeye alındı.',
            'release': TechnicalDrawingReleaseDetailSerializer(release, context={'request': request}).data,
            'topic': JobOrderDiscussionTopicDetailSerializer(topic, context={'request': request}).data
        })

    @action(detail=True, methods=['post'])
    def self_revision(self, request, pk=None):
        """
        Designer self-initiates a revision.
        Immediate hold - no approval needed since designer is initiating.
        """
        release = self.get_object()

        # Validate release status
        if release.status != 'released':
            return Response(
                {'status': 'error', 'message': 'Sadece yayınlanmış çizimler için revizyon başlatılabilir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = SelfRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason = serializer.validated_data['reason']

        # Update release status
        release.status = 'in_revision'
        release.save(update_fields=['status', 'updated_at'])

        # Put job order on hold
        job_order = release.job_order
        job_order.hold(reason=f"Revizyon: Rev.{release.revision_code or release.revision_number}")

        # Uncomplete design department task
        design_task = job_order.department_tasks.filter(
            department='design',
            parent__isnull=True
        ).first()
        if design_task and design_task.status == 'completed':
            design_task.uncomplete()

        # Send notifications
        from .signals import send_self_revision_notifications
        send_self_revision_notifications(release, reason, request.user)

        return Response({
            'status': 'success',
            'message': 'Revizyon başlatıldı. İş emri beklemeye alındı.',
            'release': TechnicalDrawingReleaseDetailSerializer(release, context={'request': request}).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def complete_revision(self, request, pk=None):
        """
        Complete the revision and create a new release.
        Resumes the job order automatically.
        """
        release = self.get_object()

        # Validate release status
        if release.status != 'in_revision':
            return Response(
                {'status': 'error', 'message': 'Sadece revizyon yapılan çizimler tamamlanabilir.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CompleteRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        folder_path = serializer.validated_data['folder_path']
        changelog = serializer.validated_data['changelog']
        revision_code = serializer.validated_data.get('revision_code', '')
        hardcopy_count = serializer.validated_data.get('hardcopy_count', 0)
        topic_content = serializer.validated_data.get('topic_content', '')

        # Mark old release as superseded
        release.status = 'superseded'
        release.save(update_fields=['status', 'updated_at'])

        # Mark revision topic as resolved
        active_revision_topic = release.revision_topics.filter(
            revision_status='in_progress',
            is_deleted=False
        ).first()
        if active_revision_topic:
            active_revision_topic.revision_status = 'resolved'
            active_revision_topic.save(update_fields=['revision_status', 'updated_at'])

        # Create new release
        new_release = TechnicalDrawingRelease.objects.create(
            job_order=release.job_order,
            revision_number=TechnicalDrawingRelease.get_next_revision_number(release.job_order),
            revision_code=revision_code,
            folder_path=folder_path,
            changelog=changelog,
            hardcopy_count=hardcopy_count,
            status='released',
            released_by=request.user
        )

        # Create release topic
        topic_title = f"Teknik Çizim Yayını - Rev.{new_release.revision_code or new_release.revision_number}"
        content = topic_content or changelog

        new_topic = JobOrderDiscussionTopic.objects.create(
            job_order=release.job_order,
            title=topic_title,
            content=content,
            priority='normal',
            topic_type='drawing_release',
            created_by=request.user
        )

        # Extract and set mentions
        mentioned_users = new_topic.extract_mentions()
        if mentioned_users.exists():
            new_topic.mentioned_users.set(mentioned_users)

        # Link topic to release
        new_release.release_topic = new_topic
        new_release.save(update_fields=['release_topic'])

        # Complete the design department task
        job_order = release.job_order
        design_task = job_order.department_tasks.filter(
            department='design',
            parent__isnull=True
        ).first()
        if design_task and design_task.status == 'in_progress':
            design_task.complete(user=request.user)

        # Resume job order
        job_order.resume()

        # Send notifications
        from .signals import send_revision_completed_notifications
        send_revision_completed_notifications(new_release, new_topic, active_revision_topic, request.user)

        return Response({
            'status': 'success',
            'message': 'Revizyon tamamlandı. Yeni çizim yayınlandı ve iş emri devam ediyor.',
            'release': TechnicalDrawingReleaseDetailSerializer(new_release, context={'request': request}).data,
            'topic': JobOrderDiscussionTopicDetailSerializer(new_topic, context={'request': request}).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reject_revision(self, request, pk=None):
        """
        Reject a pending revision request.
        No status changes to release or job order.
        """
        release = self.get_object()

        serializer = RejectRevisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        topic_id = serializer.validated_data['topic_id']
        reason = serializer.validated_data['reason']

        # Get the pending revision topic
        try:
            topic = release.revision_topics.get(
                id=topic_id,
                revision_status='pending',
                is_deleted=False
            )
        except JobOrderDiscussionTopic.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'Bekleyen revizyon talebi bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update topic status
        topic.revision_status = 'rejected'
        topic.save(update_fields=['revision_status', 'updated_at'])

        # Add rejection comment
        JobOrderDiscussionComment.objects.create(
            topic=topic,
            content=f"**Revizyon Reddedildi**\n\n{reason}",
            created_by=request.user
        )

        # Send notifications
        from .signals import send_revision_rejected_notifications
        send_revision_rejected_notifications(release, topic, reason, request.user)

        return Response({
            'status': 'success',
            'message': 'Revizyon talebi reddedildi.',
            'topic': JobOrderDiscussionTopicDetailSerializer(topic, context={'request': request}).data
        })

    # -------------------------------------------------------------------------
    # Convenience endpoints
    # -------------------------------------------------------------------------

    @action(detail=False, methods=['get'])
    def current(self, request):
        """
        Get the current (latest released) drawing for a job order.
        Query param: job_order (required)
        """
        job_order_no = request.query_params.get('job_order')
        if not job_order_no:
            return Response(
                {'status': 'error', 'message': 'job_order parametresi gerekli.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            job_order = JobOrder.objects.get(job_no=job_order_no)
        except JobOrder.DoesNotExist:
            return Response(
                {'status': 'error', 'message': 'İş emri bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        current_release = TechnicalDrawingRelease.objects.filter(
            job_order=job_order,
            status='released'
        ).order_by('-revision_number').first()

        if not current_release:
            return Response(
                {'status': 'error', 'message': 'Bu iş emri için yayınlanmış çizim bulunamadı.'},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = TechnicalDrawingReleaseDetailSerializer(current_release, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def status_choices(self, request):
        """Get available status choices."""
        return Response([
            {'value': choice[0], 'label': choice[1]}
            for choice in TechnicalDrawingRelease.STATUS_CHOICES
        ])


# =============================================================================
# Cost ViewSets
# =============================================================================

class JobOrderProcurementLineViewSet(viewsets.ModelViewSet):
    """
    CRUD for procurement cost lines.

    Extra actions:
      GET  /procurement-lines/preview/?job_order={job_no}
           Pre-populate lines from PlanningRequestItem + purchase prices (no save).

      POST /procurement-lines/submit/
           Atomically replace all lines for a job order.
    """
    permission_classes = [IsCostAuthorized]
    from .serializers import JobOrderProcurementLineSerializer as _Ser
    serializer_class = _Ser
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {'job_order': ['exact']}
    ordering = ['order']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        from .models import JobOrderProcurementLine
        return JobOrderProcurementLine.objects.select_related('item', 'planning_request_item')

    def get_serializer_class(self):
        from .serializers import JobOrderProcurementLineSerializer
        return JobOrderProcurementLineSerializer

    @action(detail=False, methods=['get'], url_path='preview')
    def preview(self, request):
        """
        Returns pre-populated procurement lines from PlanningRequestItem records.
        Uses the price lookup cascade:
          1. PurchaseOrderLine via FK (PurchaseRequestItem.planning_request_item = pri)
          2. PurchaseOrderLine via M2M (PurchaseRequest.planning_request_items ∋ pri, same item)
          3. Recommended ItemOffer for this planning item (FK path)
          4. Any ItemOffer for this planning item (FK path)
          5. Latest historical PurchaseOrderLine for the same Item (any job)
        Does NOT save anything.
        """
        from .serializers import ProcurementPreviewLineSerializer
        from planning.models import PlanningRequestItem
        from procurement.models import PurchaseOrderLine
        from projects.services.costing import convert_to_eur
        from decimal import Decimal

        def ex_tax(gross, tax_rate):
            """Return the ex-tax (net) price given a gross price and a tax rate in %."""
            rate = tax_rate or Decimal('0')
            if rate == 0:
                return gross
            return gross / (1 + rate / Decimal('100'))

        job_no = request.query_params.get('job_order')
        if not job_no:
            return Response({'detail': 'job_order query param is required.'}, status=400)

        pr_items = (
            PlanningRequestItem.objects
            .filter(job_no=job_no)
            .select_related('item')
            .prefetch_related(
                'purchase_request_items__offers__supplier_offer',
                'purchase_request_items__po_lines__po',
            )
            .order_by('id')
        )

        results = []
        for idx, pri in enumerate(pr_items):
            unit_price_eur = None
            original_unit_price = None
            original_currency = None
            price_source = 'none'
            ref_date = None

            # --- Tier 1: PurchaseOrderLine ---
            po_line = None
            for pri_item in pri.purchase_request_items.exclude(purchase_request__status='cancelled'):
                for line in pri_item.po_lines.exclude(po__status='cancelled'):
                    po_line = line
                    break
                if po_line:
                    break
            if po_line:
                price_source = 'po_line'
                net = ex_tax(po_line.unit_price, po_line.po.tax_rate)
                original_unit_price = net
                original_currency = po_line.po.currency
                ref_date = (
                    po_line.po.ordered_at.date() if po_line.po.ordered_at
                    else po_line.po.created_at.date()
                )
                unit_price_eur = convert_to_eur(net, original_currency, ref_date)

            # --- Tier 2: PurchaseOrderLine via M2M path ---
            # Covers cases where PurchaseRequestItem.planning_request_item is NULL but the
            # PurchaseRequest has this PlanningRequestItem in its planning_request_items M2M.
            if price_source == 'none' and pri.item_id:
                m2m_po_line = (
                    PurchaseOrderLine.objects
                    .filter(
                        purchase_request_item__purchase_request__planning_request_items=pri,
                        purchase_request_item__item_id=pri.item_id,
                    )
                    .exclude(purchase_request_item__purchase_request__status='cancelled')
                    .exclude(po__status='cancelled')
                    .select_related('po')
                    .order_by('-po__ordered_at', '-po__created_at', '-id')
                    .first()
                )
                if m2m_po_line:
                    price_source = 'po_line'
                    net = ex_tax(m2m_po_line.unit_price, m2m_po_line.po.tax_rate)
                    original_unit_price = net
                    original_currency = m2m_po_line.po.currency
                    ref_date = (
                        m2m_po_line.po.ordered_at.date() if m2m_po_line.po.ordered_at
                        else m2m_po_line.po.created_at.date()
                    )
                    unit_price_eur = convert_to_eur(net, original_currency, ref_date)

            # --- Tier 3: Recommended ItemOffer (FK path) ---
            if price_source == 'none':
                offer = None
                for pri_item in pri.purchase_request_items.exclude(purchase_request__status='cancelled'):
                    for o in pri_item.offers.filter(is_recommended=True).order_by('-id'):
                        offer = o
                        break
                    if offer:
                        break
                if offer:
                    price_source = 'recommended_offer'
                    net = ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
                    original_unit_price = net
                    original_currency = offer.supplier_offer.currency
                    ref_date = offer.supplier_offer.created_at.date()
                    unit_price_eur = convert_to_eur(net, original_currency, ref_date)

            # --- Tier 4: Any ItemOffer (FK path) ---
            if price_source == 'none':
                offer = None
                for pri_item in pri.purchase_request_items.exclude(purchase_request__status='cancelled'):
                    for o in pri_item.offers.order_by('-id'):
                        offer = o
                        break
                    if offer:
                        break
                if offer:
                    price_source = 'any_offer'
                    net = ex_tax(offer.unit_price, offer.supplier_offer.tax_rate)
                    original_unit_price = net
                    original_currency = offer.supplier_offer.currency
                    ref_date = offer.supplier_offer.created_at.date()
                    unit_price_eur = convert_to_eur(net, original_currency, ref_date)

            # --- Tier 5: Latest historical PO line for this item (any job) ---
            if price_source == 'none' and pri.item_id:
                hist_line = (
                    PurchaseOrderLine.objects
                    .filter(purchase_request_item__item_id=pri.item_id)
                    .exclude(purchase_request_item__purchase_request__status='cancelled')
                    .exclude(po__status='cancelled')
                    .select_related('po')
                    .order_by('-po__ordered_at', '-po__created_at', '-id')
                    .first()
                )
                if hist_line:
                    price_source = 'historical_po'
                    net = ex_tax(hist_line.unit_price, hist_line.po.tax_rate)
                    original_unit_price = net
                    original_currency = hist_line.po.currency
                    ref_date = (
                        hist_line.po.ordered_at.date() if hist_line.po.ordered_at
                        else hist_line.po.created_at.date()
                    )
                    unit_price_eur = convert_to_eur(net, original_currency, ref_date)

            results.append({
                'planning_request_item': pri.pk,
                'item': pri.item_id,
                'item_code': pri.item.code if pri.item else None,
                'item_name': pri.item.name if pri.item else None,
                'item_unit': pri.item.unit if pri.item else None,
                'item_description': pri.item_description or (pri.item.name if pri.item else ''),
                'quantity': pri.quantity,
                'unit_price_eur': unit_price_eur,
                'original_unit_price': original_unit_price,
                'original_currency': original_currency,
                'price_source': price_source,
                'price_date': ref_date,
                'order': idx,
            })

        serializer = ProcurementPreviewLineSerializer(results, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='submit')
    def submit(self, request):
        """
        Atomically replace all procurement cost lines for a job order.
        Computes amount_eur = quantity × unit_price server-side.
        """
        from .serializers import ProcurementLinesSubmitSerializer, JobOrderProcurementLineSerializer
        from .models import JobOrderProcurementLine
        from decimal import Decimal

        serializer = ProcurementLinesSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job_order = serializer.validated_data['job_order']
        lines_data = serializer.validated_data.get('lines', [])

        with transaction.atomic():
            JobOrderProcurementLine.objects.filter(job_order=job_order).delete()
            new_lines = [
                JobOrderProcurementLine(
                    job_order=job_order,
                    item=line.get('item'),
                    item_description=line.get('item_description', ''),
                    quantity=line['quantity'],
                    unit_price=line['unit_price'],
                    amount_eur=Decimal(str(line['quantity'])) * Decimal(str(line['unit_price'])),
                    planning_request_item=line.get('planning_request_item'),
                    order=line.get('order', 0),
                )
                for line in lines_data
            ]
            created = JobOrderProcurementLine.objects.bulk_create(new_lines)
            from projects.services.costing import recompute_job_cost_summary
            recompute_job_cost_summary(job_order.job_no)

        result_serializer = JobOrderProcurementLineSerializer(created, many=True)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class JobOrderQCCostLineViewSet(viewsets.ModelViewSet):
    """
    QC cost lines per job order.

    POST /qc-cost-lines/submit/
         Atomically replace all QC lines for a job order.
    """
    permission_classes = [IsCostAuthorized]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {'job_order': ['exact']}
    ordering = ['-date', 'id']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        from .models import JobOrderQCCostLine
        return JobOrderQCCostLine.objects.select_related('created_by')

    def get_serializer_class(self):
        from .serializers import JobOrderQCCostLineSerializer
        return JobOrderQCCostLineSerializer

    @action(detail=False, methods=['post'], url_path='submit')
    def submit(self, request):
        """Atomically replace all QC cost lines for a job order."""
        from .serializers import QCLinesSubmitSerializer, JobOrderQCCostLineSerializer
        from .models import JobOrderQCCostLine

        serializer = QCLinesSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job_order = serializer.validated_data['job_order']
        lines_data = serializer.validated_data.get('lines', [])

        with transaction.atomic():
            JobOrderQCCostLine.objects.filter(job_order=job_order).delete()
            new_lines = [
                JobOrderQCCostLine(
                    job_order=job_order,
                    created_by=request.user,
                    description=line['description'],
                    amount=line['amount_eur'],
                    currency='EUR',
                    amount_eur=line['amount_eur'],
                    date=line.get('date'),
                    notes=line.get('notes', ''),
                )
                for line in lines_data
            ]
            created = JobOrderQCCostLine.objects.bulk_create(new_lines)
            from projects.services.costing import recompute_job_cost_summary
            recompute_job_cost_summary(job_order.job_no)

        return Response(
            JobOrderQCCostLineSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class JobOrderShippingCostLineViewSet(viewsets.ModelViewSet):
    """
    Shipping cost lines per job order.

    POST /shipping-cost-lines/submit/
         Atomically replace all shipping lines for a job order.
    """
    permission_classes = [IsCostAuthorized]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {'job_order': ['exact']}
    ordering = ['-date', 'id']
    http_method_names = ['get', 'post', 'delete', 'head', 'options']

    def get_queryset(self):
        from .models import JobOrderShippingCostLine
        return JobOrderShippingCostLine.objects.select_related('created_by')

    def get_serializer_class(self):
        from .serializers import JobOrderShippingCostLineSerializer
        return JobOrderShippingCostLineSerializer

    @action(detail=False, methods=['post'], url_path='submit', permission_classes=[permissions.IsAuthenticated])
    def submit(self, request):
        """Atomically replace all shipping cost lines for a job order."""
        from .serializers import ShippingLinesSubmitSerializer, JobOrderShippingCostLineSerializer
        from .models import JobOrderShippingCostLine

        serializer = ShippingLinesSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        job_order = serializer.validated_data['job_order']
        lines_data = serializer.validated_data.get('lines', [])

        with transaction.atomic():
            JobOrderShippingCostLine.objects.filter(job_order=job_order).delete()
            new_lines = [
                JobOrderShippingCostLine(
                    job_order=job_order,
                    created_by=request.user,
                    description=line['description'],
                    amount=line['amount_eur'],
                    currency='EUR',
                    amount_eur=line['amount_eur'],
                    date=line.get('date'),
                    notes=line.get('notes', ''),
                )
                for line in lines_data
            ]
            created = JobOrderShippingCostLine.objects.bulk_create(new_lines)
            from projects.services.costing import recompute_job_cost_summary
            recompute_job_cost_summary(job_order.job_no)

        return Response(
            JobOrderShippingCostLineSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )
