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
        return PurchaseRequest.objects.all()
    
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
    
    @action(detail=False, methods=['get'])
    def pending_approval(self, request):
        """Get purchase requests pending approval (for managers)"""
        if not request.user.has_perm('app_name.approve_purchaserequests'):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        queryset = PurchaseRequest.objects.filter(status='submitted')
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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
    