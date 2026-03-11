from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    OfferTemplate,
    OfferTemplateNode,
    SalesOffer,
    SalesOfferItem,
    SalesOfferFile,
    SalesOfferPriceRevision,
)
from .permissions import IsSalesUser
from .serializers import (
    OfferTemplateListSerializer,
    OfferTemplateDetailSerializer,
    OfferTemplateCreateUpdateSerializer,
    OfferTemplateNodeSerializer,
    OfferTemplateNodeCreateUpdateSerializer,
    SalesOfferListSerializer,
    SalesOfferDetailSerializer,
    SalesOfferCreateSerializer,
    SalesOfferUpdateSerializer,
    SalesOfferItemSerializer,
    SalesOfferItemCreateSerializer,
    SalesOfferFileSerializer,
    SalesOfferFileUploadSerializer,
    SalesOfferPriceRevisionSerializer,
    SendConsultationsSerializer,
    SubmitForApprovalSerializer,
    RecordApprovalDecisionSerializer,
    AddItemsSerializer,
    UpdateConsultationSerializer,
)
from . import services


# =============================================================================
# Offer Template ViewSet
# =============================================================================

class OfferTemplateViewSet(viewsets.ModelViewSet):
    """
    Product catalog management.
    All authenticated users can browse; only sales/management can create/modify.

    list/retrieve: GET /sales/offer-templates/
    create:        POST /sales/offer-templates/          (IsSalesUser)
    update:        PATCH /sales/offer-templates/{id}/    (IsSalesUser)
    nodes:         GET/POST/PATCH/DELETE /sales/offer-templates/{id}/nodes/
    """
    queryset = OfferTemplate.objects.all()
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy',
                           'add_node', 'update_node', 'delete_node',
                           ] or (self.action == 'node_detail' and self.request.method in ['PATCH', 'DELETE']):
            return [IsSalesUser()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == 'list':
            return OfferTemplateListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return OfferTemplateCreateUpdateSerializer
        return OfferTemplateDetailSerializer

    def get_queryset(self):
        qs = OfferTemplate.objects.all()
        if self.action == 'list':
            show_inactive = self.request.query_params.get('show_inactive', 'false').lower() == 'true'
            if not show_inactive:
                qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            OfferTemplateDetailSerializer(serializer.instance).data,
            status=status.HTTP_201_CREATED,
        )

    # ------------------------------------------------------------------ nodes

    @action(detail=True, methods=['get', 'post'], url_path='nodes')
    def nodes(self, request, pk=None):
        template = self.get_object()

        if request.method == 'GET':
            roots = template.nodes.filter(parent__isnull=True, is_active=True).order_by('sequence')
            serializer = OfferTemplateNodeSerializer(roots, many=True)
            return Response(serializer.data)

        # POST — create a new node
        serializer = OfferTemplateNodeCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = serializer.save(template=template)
        return Response(
            OfferTemplateNodeCreateUpdateSerializer(node).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get', 'patch', 'delete'], url_path=r'nodes/(?P<node_pk>\d+)')
    def node_detail(self, request, pk=None, node_pk=None):
        template = self.get_object()
        try:
            node = template.nodes.get(pk=node_pk)
        except OfferTemplateNode.DoesNotExist:
            return Response({'detail': 'Node bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            children = node.children.filter(is_active=True).order_by('sequence')
            return Response(OfferTemplateNodeSerializer(children, many=True).data)

        if request.method == 'PATCH':
            serializer = OfferTemplateNodeCreateUpdateSerializer(node, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        # DELETE
        node.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =============================================================================
# Sales Offer ViewSet
# =============================================================================

class SalesOfferViewSet(viewsets.ModelViewSet):
    """
    Full CRUD + workflow actions for sales offers.
    Only IsSalesUser can access any endpoint.

    Standard CRUD:
      GET    /sales/offers/              list
      POST   /sales/offers/              create
      GET    /sales/offers/{id}/         retrieve
      PATCH  /sales/offers/{id}/         partial_update

    Item management:
      POST   /sales/offers/{id}/add-items/
      PATCH  /sales/offers/{id}/items/{item_id}/
      DELETE /sales/offers/{id}/items/{item_id}/

    File management:
      GET    /sales/offers/{id}/files/
      POST   /sales/offers/{id}/files/
      DELETE /sales/offers/{id}/files/{file_id}/

    Workflow:
      POST   /sales/offers/{id}/send-consultations/
      POST   /sales/offers/{id}/propose-price/
      POST   /sales/offers/{id}/submit-approval/
      POST   /sales/offers/{id}/decide/
      POST   /sales/offers/{id}/submit-customer/
      POST   /sales/offers/{id}/mark-won/
      POST   /sales/offers/{id}/mark-lost/
      POST   /sales/offers/{id}/cancel/
      POST   /sales/offers/{id}/convert/

    Read-only extras:
      GET    /sales/offers/{id}/price-history/
      GET    /sales/offers/{id}/approval-status/
    """
    permission_classes = [IsSalesUser]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['offer_no', 'title', 'description', 'customer__name', 'customer__code']
    ordering_fields = ['offer_no', 'status', 'created_at', 'updated_at']
    ordering = ['-created_at']
    filterset_fields = {
        'status': ['exact', 'in'],
        'customer': ['exact'],
    }

    def get_queryset(self):
        return SalesOffer.objects.select_related(
            'customer', 'created_by', 'converted_job_order'
        ).prefetch_related('items', 'price_revisions', 'job_orders')

    def get_serializer_class(self):
        if self.action == 'list':
            return SalesOfferListSerializer
        if self.action == 'create':
            return SalesOfferCreateSerializer
        if self.action in ['update', 'partial_update']:
            return SalesOfferUpdateSerializer
        return SalesOfferDetailSerializer

    def perform_create(self, serializer):
        from django.utils import timezone
        offer_no = services.generate_offer_no(timezone.now().year)
        serializer.save(created_by=self.request.user, offer_no=offer_no)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            SalesOfferDetailSerializer(serializer.instance, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            SalesOfferDetailSerializer(serializer.instance, context={'request': request}).data
        )

    # ------------------------------------------------------------------ items

    @action(detail=True, methods=['get'], url_path='items')
    def items(self, request, pk=None):
        offer = self.get_object()
        return Response(SalesOfferItemSerializer(offer.items.all(), many=True).data)

    @action(detail=True, methods=['post'], url_path='add-items')
    def add_items(self, request, pk=None):
        offer = self.get_object()
        if offer.status in ('won', 'cancelled'):
            return Response(
                {'detail': 'Kazanılmış veya iptal edilmiş tekliflere kalem eklenemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AddItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created = []
        for item_data in serializer.validated_data['items']:
            item = SalesOfferItem.objects.create(
                offer=offer,
                created_by=request.user,
                **item_data,
            )
            created.append(item)

        return Response(
            SalesOfferItemSerializer(created, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get', 'patch', 'delete'], url_path=r'items/(?P<item_pk>\d+)')
    def item_detail(self, request, pk=None, item_pk=None):
        offer = self.get_object()
        try:
            item = offer.items.get(pk=item_pk)
        except SalesOfferItem.DoesNotExist:
            return Response({'detail': 'Kalem bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            return Response(SalesOfferItemSerializer(item).data)

        if request.method == 'PATCH':
            serializer = SalesOfferItemCreateSerializer(item, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            if (
                item.unit_price is not None
                and offer.status in ('draft', 'consultation')
            ):
                offer.status = 'pricing'
                offer.save(update_fields=['status', 'updated_at'])
            return Response(SalesOfferItemSerializer(item).data)

        # DELETE
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------ files

    @action(detail=True, methods=['get', 'post'], url_path='files',
            parser_classes=[MultiPartParser, FormParser])
    def files(self, request, pk=None):
        offer = self.get_object()

        if request.method == 'GET':
            qs = offer.files.all()
            serializer = SalesOfferFileSerializer(qs, many=True, context={'request': request})
            return Response(serializer.data)

        # POST — upload one or more files
        files = request.FILES.getlist('file')
        if not files:
            return Response({'detail': 'En az bir dosya gereklidir.'}, status=status.HTTP_400_BAD_REQUEST)
        created = []
        upload_data = {
            'file_type': request.data.get('file_type', 'other'),
            'name': request.data.get('name', ''),
            'description': request.data.get('description', ''),
        }
        for f in files:
            data = {**upload_data, 'file': f}
            serializer = SalesOfferFileUploadSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            created.append(serializer.save(offer=offer, uploaded_by=request.user))
        return Response(
            SalesOfferFileSerializer(created, many=True, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['delete'], url_path=r'files/(?P<file_pk>\d+)')
    def file_detail(self, request, pk=None, file_pk=None):
        offer = self.get_object()
        try:
            file_obj = offer.files.get(pk=file_pk)
        except SalesOfferFile.DoesNotExist:
            return Response({'detail': 'Dosya bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)
        file_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------ workflow

    @action(detail=True, methods=['post'], url_path='send-consultations')
    def send_consultations(self, request, pk=None):
        offer = self.get_object()
        serializer = SendConsultationsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            tasks = services.send_consultations(
                offer=offer,
                departments_data=serializer.validated_data['departments'],
                user=request.user,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {'created': len(tasks), 'detail': 'Danışma görevleri oluşturuldu.'},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='submit-approval')
    def submit_approval(self, request, pk=None):
        offer = self.get_object()
        serializer = SubmitForApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            wf = services.submit_for_approval(
                offer=offer,
                user=request.user,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        from approvals.serializers import WorkflowSerializer
        return Response(
            WorkflowSerializer(wf).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'], url_path='decide')
    def decide(self, request, pk=None):
        offer = self.get_object()
        serializer = RecordApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = services.record_approval_decision(
                offer=offer,
                approver=request.user,
                approve=serializer.validated_data['approve'],
                comment=serializer.validated_data.get('comment', ''),
                counter_amount=serializer.validated_data.get('counter_amount'),
                counter_currency=serializer.validated_data.get('counter_currency', 'EUR'),
            )
        except Exception as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'outcome': result['outcome'],
            'offer_status': offer.status,
        })

    @action(detail=True, methods=['post'], url_path='submit-customer')
    def submit_customer(self, request, pk=None):
        offer = self.get_object()
        if offer.status != 'approved':
            return Response(
                {'detail': 'Sadece onaylanmış teklifler müşteriye gönderilebilir.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offer.status = 'submitted_customer'
        offer.submitted_to_customer_at = timezone.now()
        offer.save(update_fields=['status', 'submitted_to_customer_at', 'updated_at'])
        return Response(SalesOfferDetailSerializer(offer, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='mark-won')
    def mark_won(self, request, pk=None):
        """Mark the offer as won without converting to job order."""
        offer = self.get_object()
        if offer.status not in ('approved', 'submitted_customer'):
            return Response(
                {'detail': 'Teklif ancak onaylandıktan veya müşteriye gönderildikten sonra kazanıldı olarak işaretlenebilir.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offer.status = 'won'
        offer.won_at = timezone.now()
        offer.save(update_fields=['status', 'won_at', 'updated_at'])
        return Response(SalesOfferDetailSerializer(offer, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='mark-lost')
    def mark_lost(self, request, pk=None):
        offer = self.get_object()
        if offer.status not in ('approved', 'submitted_customer'):
            return Response(
                {'detail': 'Teklif ancak onaylandıktan veya müşteriye gönderildikten sonra kaybedildi olarak işaretlenebilir.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offer.status = 'lost'
        offer.lost_at = timezone.now()
        offer.save(update_fields=['status', 'lost_at', 'updated_at'])
        return Response(SalesOfferDetailSerializer(offer, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        offer = self.get_object()
        if offer.status in ('won', 'cancelled'):
            return Response(
                {'detail': 'Bu teklif zaten kapatılmış.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offer.status = 'cancelled'
        offer.cancelled_at = timezone.now()
        offer.save(update_fields=['status', 'cancelled_at', 'updated_at'])
        return Response(SalesOfferDetailSerializer(offer, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='revert-to-draft')
    def revert_to_draft(self, request, pk=None):
        offer = self.get_object()
        if offer.converted_job_order_id:
            return Response(
                {'detail': 'Bu teklif bir iş emrine dönüştürülmüştür, taslağa geri alınamaz.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if offer.status == 'draft':
            return Response(
                {'detail': 'Teklif zaten taslak durumunda.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        offer.status = 'draft'
        offer.approval_round = 0
        offer.submitted_to_customer_at = None
        offer.won_at = None
        offer.lost_at = None
        offer.cancelled_at = None
        offer.save(update_fields=[
            'status', 'approval_round',
            'submitted_to_customer_at', 'won_at', 'lost_at', 'cancelled_at',
            'updated_at',
        ])
        return Response(SalesOfferDetailSerializer(offer, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='convert')
    def convert(self, request, pk=None):
        offer = self.get_object()
        file_ids = request.data.get('file_ids', [])
        if not isinstance(file_ids, list):
            return Response({'detail': 'file_ids must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            job = services.convert_offer_to_job_order(
                offer=offer, user=request.user,
                file_ids=file_ids,
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'detail': 'Teklif iş emrine dönüştürüldü.',
            'job_no': job.job_no,
            'offer_no': offer.offer_no,
        }, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------ read-only extras

    @action(detail=True, methods=['get'], url_path='consultations')
    def consultations(self, request, pk=None):
        """
        Return consultation tasks for this offer, grouped by department.
        Each entry includes the task's notes (department response) and completion files.
        """
        offer = self.get_object()
        tasks = offer.department_tasks.select_related(
            'assigned_to', 'created_by', 'completed_by'
        ).prefetch_related('completion_files').order_by('department', 'created_at')

        grouped = {}
        for task in tasks:
            dept = task.department
            if dept not in grouped:
                grouped[dept] = {
                    'department': dept,
                    'department_display': task.get_department_display(),
                    'tasks': [],
                }

            completion_files = []
            for f in task.completion_files.all():
                file_url = request.build_absolute_uri(f.file.url) if f.file else None
                completion_files.append({
                    'id': f.id,
                    'file_url': file_url,
                    'filename': f.filename,
                    'file_size': f.file_size,
                    'file_type': f.file_type,
                    'name': f.name,
                    'uploaded_at': f.uploaded_at,
                    'uploaded_by_name': f.uploaded_by.get_full_name() if f.uploaded_by else '',
                })

            grouped[dept]['tasks'].append({
                'id': task.id,
                'title': task.title,
                'status': task.status,
                'status_display': task.get_status_display(),
                'assigned_to': task.assigned_to_id,
                'assigned_to_name': task.assigned_to.get_full_name() if task.assigned_to else '',
                'notes': task.notes or '',
                'target_completion_date': task.target_completion_date,
                'started_at': task.started_at,
                'completed_at': task.completed_at,
                'completed_by_name': task.completed_by.get_full_name() if task.completed_by else '',
                'completion_files': completion_files,
            })

        return Response(list(grouped.values()))

    @action(detail=True, methods=['get', 'patch'], url_path=r'consultations/(?P<task_pk>\d+)')
    def consultation_detail(self, request, pk=None, task_pk=None):
        """
        GET  /sales/offers/{id}/consultations/{task_pk}/  — retrieve consultation detail
        PATCH /sales/offers/{id}/consultations/{task_pk}/ — update consultation
        """
        offer = self.get_object()
        try:
            task = offer.department_tasks.get(pk=task_pk)
        except offer.department_tasks.model.DoesNotExist:
            return Response({'detail': 'Danışma görevi bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            from projects.serializers import DepartmentTaskDetailSerializer
            return Response(DepartmentTaskDetailSerializer(task, context={'request': request}).data)

        serializer = UpdateConsultationSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if 'title' in data:
            task.title = data['title']
        if 'notes' in data:
            task.description = data['notes']
        if 'deadline' in data:
            task.target_completion_date = data['deadline']
        task.status = 'pending'
        task.completed_at = None
        task.completed_by = None
        task.save(update_fields=[
            'title', 'description', 'target_completion_date',
            'status', 'completed_at', 'completed_by', 'updated_at',
        ])

        if 'file_ids' in data and data['file_ids'] is not None:
            task.shared_files.set(offer.files.filter(id__in=data['file_ids']))

        from projects.serializers import DepartmentTaskDetailSerializer
        return Response(DepartmentTaskDetailSerializer(task, context={'request': request}).data)

    @action(detail=True, methods=['get'], url_path='price-history')
    def price_history(self, request, pk=None):
        offer = self.get_object()
        revisions = offer.price_revisions.order_by('created_at')
        return Response(SalesOfferPriceRevisionSerializer(revisions, many=True).data)

    @action(detail=True, methods=['get'], url_path='approval-status')
    def approval_status(self, request, pk=None):
        offer = self.get_object()
        from approvals.services import get_workflow
        wf = get_workflow(offer)
        if not wf:
            return Response({'detail': 'Aktif onay süreci bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)

        from approvals.serializers import WorkflowSerializer
        return Response(WorkflowSerializer(wf).data)
