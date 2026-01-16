from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend

from .models import Customer, JobOrder
from .serializers import (
    CustomerListSerializer,
    CustomerDetailSerializer,
    CustomerCreateUpdateSerializer,
    JobOrderListSerializer,
    JobOrderDetailSerializer,
    JobOrderCreateSerializer,
    JobOrderUpdateSerializer,
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
    ordering = ['name']
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
    def complete(self, request, job_no=None):
        """Complete the job order."""
        job_order = self.get_object()
        try:
            job_order.complete(user=request.user)
            return Response({
                'status': 'success',
                'message': 'İş emri tamamlandı.',
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

            return {
                'job_no': job.job_no,
                'title': job.title,
                'status': job.status,
                'status_display': job.get_status_display(),
                'priority': job.priority,
                'completion_percentage': job.completion_percentage,
                'target_completion_date': job.target_completion_date,
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
