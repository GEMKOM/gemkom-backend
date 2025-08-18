from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    PaymentType, Supplier, Item, PurchaseRequest, 
    PurchaseRequestItem, SupplierOffer, ItemOffer
)

class PaymentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentType
        fields = ['id', 'name']

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            'id', 'name', 'contact_person', 'phone', 'email',
            'currency', 'default_currency', 'default_payment_method',
            'is_active', 'created_at', 'updated_at'
        ]

class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ['id', 'code', 'name', 'unit']

class PurchaseRequestItemSerializer(serializers.ModelSerializer):
    item = ItemSerializer(read_only=True)
    
    class Meta:
        model = PurchaseRequestItem
        fields = [
            'id', 'item', 'quantity', 'priority',
            'specifications', 'order', 'job_no'
        ]

class ItemOfferSerializer(serializers.ModelSerializer):
    purchase_request_item = serializers.PrimaryKeyRelatedField(read_only=True)
    
    class Meta:
        model = ItemOffer
        fields = [
            'id', 'unit_price', 'total_price', 'delivery_days',
            'notes', 'is_recommended', 'purchase_request_item'
        ]

class SupplierOfferSerializer(serializers.ModelSerializer):
    supplier = SupplierSerializer(read_only=True)
    item_offers = ItemOfferSerializer(many=True, read_only=True)
    
    class Meta:
        model = SupplierOffer
        fields = [
            'id', 'supplier', 'notes', 'item_offers', 'created_at', 'updated_at'
        ]

class PurchaseRequestSerializer(serializers.ModelSerializer):
    request_items = PurchaseRequestItemSerializer(many=True, read_only=True)
    offers = SupplierOfferSerializer(many=True, read_only=True)
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    status_label = serializers.SerializerMethodField()

    def get_status_label(self, obj):
        return obj.get_status_display()
    
    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'request_number', 'title', 'description',
            'requestor', 'requestor_username', 'priority', 'status', 'status_label',
            'total_amount_eur', 'currency_rates_snapshot',
            'created_at', 'updated_at', 'submitted_at',
            'request_items', 'offers'
        ]
        read_only_fields = ['request_number', 'created_at', 'updated_at', 'submitted_at']

# Special serializer for creating purchase requests with nested data
class PurchaseRequestCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(child=serializers.DictField(), write_only=True)
    suppliers = serializers.ListField(child=serializers.DictField(), write_only=True)
    offers = serializers.DictField(write_only=True)
    recommendations = serializers.DictField(write_only=True)
    
    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'title', 'description', 'priority',
            'items', 'suppliers', 'offers', 'recommendations'
        ]
    
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        suppliers_data = validated_data.pop('suppliers')
        offers_data = validated_data.pop('offers')
        recommendations_data = validated_data.pop('recommendations')
        
        # Create purchase request
        purchase_request = PurchaseRequest.objects.create(
            **validated_data,
            requestor=self.context['request'].user
        )
        
        # Create or get items and purchase request items
        request_items = []
        for i, item_data in enumerate(items_data):
            item, created = Item.objects.get_or_create(
                code=item_data['code'],
                defaults={
                    'name': item_data['name'],
                    'unit': item_data['unit']
                }
            )
            
            request_item = PurchaseRequestItem.objects.create(
                purchase_request=purchase_request,
                item=item,
                quantity=item_data['quantity'],
                priority=item_data.get('priority', 'normal'),
                job_no=item_data.get('job_no'),
                specifications=item_data.get('specifications', ''),
                order=i
            )
            request_items.append(request_item)
        
        # Create suppliers and offers
        for supplier_data in suppliers_data:
            supplier, created = Supplier.objects.get_or_create(
                name=supplier_data['name'],
                defaults={
                    'contact_person': supplier_data.get('contact_person', ''),
                    'phone': supplier_data.get('phone', ''),
                    'email': supplier_data.get('email', ''),
                    'currency': supplier_data.get('currency', 'TRY')
                }
            )
            
            # Create supplier offer
            supplier_offer = SupplierOffer.objects.create(
                purchase_request=purchase_request,
                supplier=supplier,
                notes=''
            )
            
            # Create item offers for this supplier
            if supplier_data['id'] in offers_data:
                for item_index, offer_data in offers_data[supplier_data['id']].items():
                    item_index = int(item_index)
                    if item_index < len(request_items):
                        request_item = request_items[item_index]
                        
                        # Check if this item-supplier combination is recommended
                        is_recommended = (recommendations_data.get(str(item_index)) == supplier_data['id'])
                        
                        ItemOffer.objects.create(
                            purchase_request_item=request_item,
                            supplier_offer=supplier_offer,
                            unit_price=offer_data['unitPrice'],
                            total_price=offer_data['totalPrice'],
                            delivery_days=offer_data.get('deliveryDays'),
                            notes=offer_data.get('notes', ''),
                            is_recommended=is_recommended
                        )
        
        return purchase_request
