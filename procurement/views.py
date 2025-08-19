from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter
from procurement.filters import PurchaseRequestFilter
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status, permissions
from approvals.services import submit_purchase_request, decide
from .models import (
    PaymentType, Supplier, Item, PurchaseRequest, 
    PurchaseRequestItem, SupplierOffer, ItemOffer
)
from .serializers import (
    PaymentTypeSerializer, SupplierSerializer, ItemSerializer,
    PurchaseRequestSerializer, PurchaseRequestCreateSerializer,
    PurchaseRequestItemSerializer, SupplierOfferSerializer, ItemOfferSerializer
)
from django.db.models import Exists, OuterRef, F, Q
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status, permissions

from approvals.models import PRApprovalStageInstance, PRApprovalDecision

class PaymentTypeViewSet(viewsets.ModelViewSet):
    queryset = PaymentType.objects.all()
    serializer_class = PaymentTypeSerializer
    permission_classes = [permissions.IsAuthenticated]

class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = Supplier.objects.filter(is_active=True)
        name = self.request.query_params.get('name', None)
        if name:
            queryset = queryset.filter(name__icontains=name)
        return queryset

class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = Item.objects.all()
        code = self.request.query_params.get('code', None)
        name = self.request.query_params.get('name', None)
        if code:
            queryset = queryset.filter(code__icontains=code)
        if name:
            queryset = queryset.filter(name__icontains=name)
        return queryset

class PurchaseRequestViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequest.objects.all()
    serializer_class = PurchaseRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PurchaseRequestFilter
    ordering_fields = ['id', 'title', 'requestor', 'priority', 'status', 'created_at', 'total_amount_eur']  # Add any fields you want to allow
    ordering = ['-id']  # Default ordering
    
    def get_queryset(self):
        return (
            PurchaseRequest.objects
            .select_related('requestor')
            .prefetch_related(
                'request_items__item',
                'offers__supplier',
                'approval_workflow__stage_instances',
                'approval_workflow__stage_instances__decisions__approver',
            )
        )
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseRequestCreateSerializer
        return PurchaseRequestSerializer
    
    @action(detail=True, methods=["POST"], permission_classes=[permissions.IsAuthenticated])
    def submit(self, request, pk=None):
        pr = self.get_object()
        try:
            submit_purchase_request(pr, request.user)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Submitted."})

    @action(detail=True, methods=["POST"], permission_classes=[permissions.IsAuthenticated])
    def approve(self, request, pk=None):
        pr = self.get_object()
        try:
            decide(pr, request.user, approve=True, comment=request.data.get("comment",""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Approved."})

    @action(detail=True, methods=["POST"], permission_classes=[permissions.IsAuthenticated])
    def reject(self, request, pk=None):
        pr = self.get_object()
        try:
            decide(pr, request.user, approve=False, comment=request.data.get("comment",""))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=403)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"detail": "Rejected."})
    
    @action(detail=False, methods=['get'])
    def my_requests(self, request):
        """Get current user's purchase requests"""
        user = request.user
        queryset = PurchaseRequest.objects.filter(requestor=user)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def pending_approval(self, request):
        """
        PRs currently awaiting *this user's* approval:
        - PR is 'submitted'
        - current stage includes the user in approver_user_ids
        - user has not already decided on the current stage
        """

        user = request.user

        # Subquery: is there a current stage on this PR where I'm an approver and it's still open?
        open_current_stage_qs = PRApprovalStageInstance.objects.filter(
            workflow=OuterRef('approval_workflow'),
            order=OuterRef('approval_workflow__current_stage_order'),
            is_complete=False,
            is_rejected=False,
            approver_user_ids__contains=[user.id],
        )

        # Subquery: have I already decided on that current stage?
        my_decision_on_current_stage_qs = PRApprovalDecision.objects.filter(
            stage_instance__workflow=OuterRef('approval_workflow'),
            stage_instance__order=OuterRef('approval_workflow__current_stage_order'),
            approver=user,
        )

        queryset = (
            self.get_queryset()
            .filter(status='submitted')                         # only in review
            .exclude(requestor=user)                           # optional: block self-approval
            .annotate(
                is_my_open_stage=Exists(open_current_stage_qs),
                already_decided=Exists(my_decision_on_current_stage_qs),
            )
            .filter(is_my_open_stage=True, already_decided=False)
            .order_by(*self.ordering)
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def approved_by_me(self, request):
        """
        Purchase requests where I have approved (optionally filter by date range).
        Query params:
          - since: ISO datetime (include decisions made at/after this)
          - until: ISO datetime (include decisions made before this)
          - decision: 'approve' or 'reject' (default: approve)
        """
        user = request.user
        decision_type = request.query_params.get("decision", "approve")
        since = request.query_params.get("since")
        until = request.query_params.get("until")

        # Base subquery: my decisions on any stage in this PR's workflow
        my_decisions = PRApprovalDecision.objects.filter(
            stage_instance__workflow_id=OuterRef('approval_workflow__id'),
            approver=user,
        )
        if decision_type in ("approve", "reject"):
            my_decisions = my_decisions.filter(decision=decision_type)

        if since:
            my_decisions = my_decisions.filter(decided_at__gte=since)
        if until:
            my_decisions = my_decisions.filter(decided_at__lt=until)

        qs = (
            self.get_queryset()
            .annotate(i_decided=Exists(my_decisions))
            .filter(i_decided=True)
            .order_by(*self.ordering)
            .distinct()
        )

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

class PurchaseRequestItemViewSet(viewsets.ModelViewSet):
    queryset = PurchaseRequestItem.objects.all()
    serializer_class = PurchaseRequestItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        if purchase_request_id:
            return PurchaseRequestItem.objects.filter(purchase_request_id=purchase_request_id)
        return PurchaseRequestItem.objects.all()

class SupplierOfferViewSet(viewsets.ModelViewSet):
    queryset = SupplierOffer.objects.all()
    serializer_class = SupplierOfferSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        if purchase_request_id:
            return SupplierOffer.objects.filter(purchase_request_id=purchase_request_id)
        return SupplierOffer.objects.all()

class ItemOfferViewSet(viewsets.ModelViewSet):
    queryset = ItemOffer.objects.all()
    serializer_class = ItemOfferSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        purchase_request_id = self.request.query_params.get('purchase_request', None)
        supplier_offer_id = self.request.query_params.get('supplier_offer', None)
        
        queryset = ItemOffer.objects.all()
        if purchase_request_id:
            queryset = queryset.filter(supplier_offer__purchase_request_id=purchase_request_id)
        if supplier_offer_id:
            queryset = queryset.filter(supplier_offer_id=supplier_offer_id)
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def toggle_recommendation(self, request, pk=None):
        """Toggle recommendation status for an item offer"""
        item_offer = self.get_object()
        
        # Ensure only one recommendation per item
        if not item_offer.is_recommended:
            # Remove other recommendations for the same item
            ItemOffer.objects.filter(
                purchase_request_item=item_offer.purchase_request_item
            ).update(is_recommended=False)
            
            # Set this one as recommended
            item_offer.is_recommended = True
        else:
            # Remove this recommendation
            item_offer.is_recommended = False
        
        item_offer.save()
        
        return Response({'is_recommended': item_offer.is_recommended})


class StatusChoicesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in PurchaseRequest.STATUS_CHOICES
        ])
    