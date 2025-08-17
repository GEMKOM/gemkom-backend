from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
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
    
    def get_queryset(self):
        user = self.request.user
        # Users can see their own requests and all requests if they have permission
        if user.has_perm('app_name.view_all_purchaserequests'):
            return PurchaseRequest.objects.all()
        return PurchaseRequest.objects.filter(requestor=user)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseRequestCreateSerializer
        return PurchaseRequestSerializer
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit a purchase request (change status from draft to submitted)"""
        purchase_request = self.get_object()
        
        if purchase_request.status != 'draft':
            return Response(
                {'error': 'Only draft requests can be submitted'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        purchase_request.status = 'submitted'
        purchase_request.submitted_at = timezone.now()
        purchase_request.save()
        
        return Response({'status': 'submitted'})
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a purchase request"""
        purchase_request = self.get_object()
        
        if purchase_request.status != 'submitted':
            return Response(
                {'error': 'Only submitted requests can be approved'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        purchase_request.status = 'approved'
        purchase_request.save()
        
        return Response({'status': 'approved'})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a purchase request"""
        purchase_request = self.get_object()
        
        if purchase_request.status not in ['submitted', 'approved']:
            return Response(
                {'error': 'Only submitted or approved requests can be rejected'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        purchase_request.status = 'rejected'
        purchase_request.save()
        
        return Response({'status': 'rejected'})
    
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
