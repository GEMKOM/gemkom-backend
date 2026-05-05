from django.utils import timezone
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.contrib.contenttypes.models import ContentType
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
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from .serializers import (
    OfferTemplateListSerializer,
    OfferTemplateDetailSerializer,
    OfferTemplateCreateUpdateSerializer,
    OfferTemplateNodeSerializer,
    OfferTemplateNodeCreateUpdateSerializer,
    NodeSearchResultSerializer,
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
    SetPricesSerializer,
    BulkUpdateItemsSerializer,
    BulkDeleteItemsSerializer,
    UpdateConsultationSerializer,
    SalesOfferApprovalPageSerializer,
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
            return [IsAuthenticated()]
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

    @action(detail=False, methods=['get'], url_path='nodes/search')
    def search_nodes(self, request):
        """
        GET /sales/offer-templates/nodes/search/?q=<query>
        Optional: ?template=<id>  &  ?is_active=true|false|all
        """
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response(
                {'detail': 'q must be at least 2 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = (
            OfferTemplateNode.objects
            .select_related(
                'template',
                'parent',
                'parent__parent',
                'parent__parent__parent',
                'parent__parent__parent__parent',
            )
            .filter(
                Q(title__icontains=q) |
                Q(code__icontains=q) |
                Q(description__icontains=q)
            )
        )

        is_active_param = request.query_params.get('is_active', 'true').lower()
        if is_active_param != 'all':
            qs = qs.filter(is_active=(is_active_param != 'false'))

        if template_id := request.query_params.get('template'):
            qs = qs.filter(template_id=template_id)

        qs = qs.order_by('template__name', 'sequence')[:100]
        return Response(NodeSearchResultSerializer(qs, many=True).data)

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
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['offer_no', 'title', 'description', 'customer__name', 'customer__code']
    ordering_fields = ['offer_no', 'status', 'created_at', 'updated_at']
    ordering = ['-created_at']
    filterset_fields = {
        'status': ['exact', 'in'],
        'customer': ['exact'],
        'created_by': ['exact'],
    }

    def get_queryset(self):
        from approvals.models import ApprovalWorkflow, ApprovalStageInstance
        user = self.request.user
        ct = ContentType.objects.get_for_model(SalesOffer)

        pending_for_me = ApprovalStageInstance.objects.filter(
            workflow__content_type=ct,
            workflow__object_id=OuterRef('pk'),
            workflow__is_complete=False,
            workflow__is_rejected=False,
            workflow__is_cancelled=False,
            is_complete=False,
            is_rejected=False,
            approver_user_ids__contains=[user.id],
        )

        qs = (
            SalesOffer.objects
            .select_related('customer', 'created_by', 'converted_job_order')
            .prefetch_related('items')
            .annotate(needs_my_approval=Exists(pending_for_me))
            .order_by('-needs_my_approval', '-created_at')
        )
        if self.action != 'list':
            qs = qs.prefetch_related('price_revisions', 'job_orders')
        return qs

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        # Always surface offers awaiting the current user's approval at the top,
        # regardless of whatever ordering the frontend requested.
        current_ordering = queryset.query.order_by
        if current_ordering and current_ordering[0] != '-needs_my_approval':
            queryset = queryset.order_by('-needs_my_approval', *current_ordering)
        return queryset

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
        qs = offer.items.select_related('template_node').prefetch_related('children').filter(parent__isnull=True)
        return Response(SalesOfferItemSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='add-items')
    def add_items(self, request, pk=None):
        """
        Accepts a list of items. Each item may have:
          - _ref: optional client-assigned temp ID (string)
          - parent_ref: references another item's _ref in this same request
        Items are processed in order; parent_ref must reference a _ref that
        appears earlier in the list.
        """
        offer = self.get_object()
        _TERMINAL = ('won', 'lost', 'cancelled', 'converted')
        if offer.status in _TERMINAL:
            return Response(
                {'detail': 'Bu durumda teklife kalem eklenemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_items = request.data.get('items', [])
        if not raw_items:
            return Response(
                {'detail': 'En az bir kalem girilmelidir.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ref_map = {}   # _ref string → created SalesOfferItem
        created = []
        errors = []

        for idx, raw in enumerate(raw_items):
            ref = raw.get('_ref')
            parent_ref = raw.get('parent_ref')

            # Strip meta fields before validation
            item_data = {k: v for k, v in raw.items() if k not in ('_ref', 'parent_ref')}

            # Resolve parent_ref → parent SalesOfferItem instance
            if parent_ref is not None:
                if parent_ref not in ref_map:
                    errors.append({
                        'index': idx,
                        'parent_ref': f"'{parent_ref}' not found — it must appear earlier in the list with a matching _ref.",
                    })
                    continue
                item_data['parent'] = ref_map[parent_ref].pk

            serializer = SalesOfferItemCreateSerializer(
                data=item_data,
                context={'offer': offer},
            )
            if not serializer.is_valid():
                errors.append({'index': idx, 'errors': serializer.errors})
                continue

            item = SalesOfferItem.objects.create(
                offer=offer,
                created_by=request.user,
                **serializer.validated_data,
            )
            created.append(item)
            if ref:
                ref_map[ref] = item

        if errors:
            return Response({'detail': 'Bazı kalemler eklenemedi.', 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)

        if offer.status in ('pending_approval', 'approved', 'submitted_customer'):
            services.rollback_to_pricing(offer)

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

        _TERMINAL = ('won', 'lost', 'cancelled', 'converted')

        if request.method == 'PATCH':
            if offer.status in _TERMINAL:
                return Response(
                    {'detail': 'Bu durumda kalem güncellenemez.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            serializer = SalesOfferItemCreateSerializer(item, data=request.data, partial=True, context={'offer': offer})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            if offer.status in ('draft', 'consultation'):
                if item.unit_price is not None:
                    offer.status = 'pricing'
                    offer.save(update_fields=['status', 'updated_at'])
            elif offer.status in ('pending_approval', 'approved', 'submitted_customer'):
                services.rollback_to_pricing(offer)
            return Response(SalesOfferItemSerializer(item).data)

        # DELETE
        if offer.status in _TERMINAL:
            return Response(
                {'detail': 'Bu durumda kalem silinemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item.delete()
        if offer.status in ('pending_approval', 'approved', 'submitted_customer'):
            services.rollback_to_pricing(offer)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------------ files

    @action(detail=True, methods=['post'], url_path='set-prices')
    def set_prices(self, request, pk=None):
        """
        Bulk-set prices, quantities, and pricing mode in one atomic request.

        POST /sales/offers/{id}/set-prices/
        {
          "pricing_mode": "flat",
          "shipping_price": 2500,
          "items": [
            { "id": 12, "unit_price": 120000, "quantity": 1, "weight_kg": 4500 },
            { "id": 15, "unit_price": 45000,  "quantity": 2 }
          ]
        }
        """
        offer = self.get_object()
        _TERMINAL = ('won', 'lost', 'cancelled', 'converted')
        if offer.status in _TERMINAL:
            return Response(
                {'detail': 'Bu durumda teklif fiyatlandırılamaz.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SetPricesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Validate all item IDs belong to this offer
        item_ids = [i['id'] for i in data['items']]
        offer_item_ids = set(offer.items.values_list('id', flat=True))
        unknown = set(item_ids) - offer_item_ids
        if unknown:
            return Response(
                {'detail': f"Item IDs not found in this offer: {sorted(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Update offer-level fields
            offer_fields = ['updated_at']
            offer.pricing_mode = data['pricing_mode']
            offer_fields.append('pricing_mode')
            if data.get('shipping_price') is not None:
                offer.shipping_price = data['shipping_price']
                offer_fields.append('shipping_price')
            offer.save(update_fields=offer_fields)

            # Bulk-update items
            items_by_id = {i.id: i for i in offer.items.all()}
            to_update = []
            update_fields = set()
            for item_data in data['items']:
                item = items_by_id[item_data['id']]
                if 'unit_price' in item_data:
                    item.unit_price = item_data['unit_price']
                    update_fields.add('unit_price')
                if 'quantity' in item_data:
                    item.quantity = item_data['quantity']
                    update_fields.add('quantity')
                if 'weight_kg' in item_data:
                    item.weight_kg = item_data['weight_kg']
                    update_fields.add('weight_kg')
                if 'delivery_period' in item_data:
                    item.delivery_period = item_data['delivery_period']
                    update_fields.add('delivery_period')
                if 'notes' in item_data:
                    item.notes = item_data['notes']
                    update_fields.add('notes')
                to_update.append(item)

            if to_update and update_fields:
                SalesOfferItem.objects.bulk_update(to_update, list(update_fields))

            # Advance status to pricing if still in draft/consultation
            if offer.status in ('draft', 'consultation'):
                offer.status = 'pricing'
                offer.save(update_fields=['status', 'updated_at'])
            elif offer.status in ('pending_approval', 'approved', 'submitted_customer'):
                services.rollback_to_pricing(offer)

        # Return fresh offer detail + items
        offer.refresh_from_db()
        return Response({
            'offer': SalesOfferDetailSerializer(offer, context={'request': request}).data,
            'items': SalesOfferItemSerializer(
                offer.items.select_related('template_node').prefetch_related('children').filter(parent__isnull=True),
                many=True,
            ).data,
        })

    @action(detail=True, methods=['post'], url_path='update-items')
    def update_items(self, request, pk=None):
        """
        Bulk-update existing offer items in one atomic request.

        POST /sales/offers/{id}/update-items/
        {
          "items": [
            { "id": 12, "title_override": "Panel - North", "quantity": 2 },
            { "id": 15, "parent": 12 }
          ]
        }
        Only fields present in each entry are updated (partial per item).
        """
        offer = self.get_object()
        _TERMINAL = ('won', 'lost', 'cancelled', 'converted')
        if offer.status in _TERMINAL:
            return Response(
                {'detail': 'Bu durumda kalemler güncellenemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = BulkUpdateItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        item_ids = [i['id'] for i in data['items']]
        offer_item_ids = set(offer.items.values_list('id', flat=True))
        unknown = set(item_ids) - offer_item_ids
        if unknown:
            return Response(
                {'detail': f"Item IDs not found in this offer: {sorted(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate parent IDs also belong to this offer
        parent_ids = {i['parent'] for i in data['items'] if 'parent' in i and i['parent'] is not None}
        unknown_parents = parent_ids - offer_item_ids
        if unknown_parents:
            return Response(
                {'detail': f"Parent item IDs not found in this offer: {sorted(unknown_parents)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _UPDATABLE = ['title_override', 'quantity', 'unit_price', 'weight_kg', 'delivery_period', 'notes', 'parent_id']

        with transaction.atomic():
            items_by_id = {i.id: i for i in offer.items.all()}
            to_update = []
            update_fields = set()

            for entry in data['items']:
                item = items_by_id[entry['id']]
                if 'title_override' in entry:
                    item.title_override = entry['title_override']
                    update_fields.add('title_override')
                if 'quantity' in entry:
                    item.quantity = entry['quantity']
                    update_fields.add('quantity')
                if 'unit_price' in entry:
                    item.unit_price = entry['unit_price']
                    update_fields.add('unit_price')
                if 'weight_kg' in entry:
                    item.weight_kg = entry['weight_kg']
                    update_fields.add('weight_kg')
                if 'delivery_period' in entry:
                    item.delivery_period = entry['delivery_period']
                    update_fields.add('delivery_period')
                if 'notes' in entry:
                    item.notes = entry['notes']
                    update_fields.add('notes')
                if 'parent' in entry:
                    item.parent_id = entry['parent']  # None clears the parent
                    update_fields.add('parent_id')
                to_update.append(item)

            if to_update and update_fields:
                SalesOfferItem.objects.bulk_update(to_update, list(update_fields))

            if offer.status in ('pending_approval', 'approved', 'submitted_customer'):
                services.rollback_to_pricing(offer)

        return Response(
            SalesOfferItemSerializer(
                offer.items.select_related('template_node').prefetch_related('children').filter(parent__isnull=True),
                many=True,
            ).data
        )

    @action(detail=True, methods=['post'], url_path='delete-items')
    def delete_items(self, request, pk=None):
        """
        Bulk-delete offer items in one atomic request.
        Deleting a parent cascades to its children automatically.

        POST /sales/offers/{id}/delete-items/
        { "ids": [12, 15, 18] }
        """
        offer = self.get_object()
        _TERMINAL = ('won', 'lost', 'cancelled', 'converted')
        if offer.status in _TERMINAL:
            return Response(
                {'detail': 'Bu durumda kalemler silinemez.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = BulkDeleteItemsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['ids']

        offer_item_ids = set(offer.items.values_list('id', flat=True))
        unknown = set(ids) - offer_item_ids
        if unknown:
            return Response(
                {'detail': f"Item IDs not found in this offer: {sorted(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            offer.items.filter(id__in=ids).delete()
            if offer.status in ('pending_approval', 'approved', 'submitted_customer'):
                services.rollback_to_pricing(offer)

        return Response(
            SalesOfferItemSerializer(
                offer.items.select_related('template_node').prefetch_related('children').filter(parent__isnull=True),
                many=True,
            ).data
        )

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
                notes=serializer.validated_data.get('notes', ''),
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

    @action(detail=True, methods=['get', 'post'], url_path='approval-status')
    def approval_status(self, request, pk=None):
        """
        GET  — Full approval page payload: offer info, items, price history,
               all workflows, and whether the current user can decide.
        POST — Submit an approval decision (same as /decide/ but accessible
               from the approval link page without separate auth context).
               Body: { approve: bool, comment?: str, counter_amount?: decimal,
                       counter_currency?: str }
        """
        offer = self.get_object()

        if request.method == 'POST':
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

            # Refresh offer from DB so serializer sees updated status
            offer.refresh_from_db()
            return Response({
                'outcome': result['outcome'],
                'offer': SalesOfferApprovalPageSerializer(offer, context={'request': request}).data,
            })

        return Response(
            SalesOfferApprovalPageSerializer(offer, context={'request': request}).data
        )
