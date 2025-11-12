from procurement.services import compute_vat_carry_map
from rest_framework import serializers
from django.utils import timezone

from approvals.serializers import WorkflowSerializer
from .models import (
    PaymentSchedule, PaymentTerms, PurchaseOrder, PurchaseOrderLine, PurchaseOrderLineAllocation, PurchaseRequestDraft, PurchaseRequestItemAllocation, Supplier, Item, PurchaseRequest,
    PurchaseRequestItem, SupplierOffer, ItemOffer, DepartmentRequest
)
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from approvals.models import ApprovalWorkflow

class PaymentTermsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerms
        fields = ["id", "name", "code", "is_custom", "active", "default_lines", "created_at", "updated_at"]

    def validate_default_lines(self, value):
        """
        Validate that the sum of percentages in default_lines is exactly 100,
        unless the list is empty (allowed for fully custom terms).
        """
        if not value:
            return value  # Empty list is valid

        total = sum(Decimal(str(line.get("percentage") or 0)) for line in value)
        if total != Decimal("100.00"):
            raise serializers.ValidationError(f"The sum of percentages in default_lines must be exactly 100. The current sum is {total}.")
        return value

class PaymentScheduleSerializer(serializers.ModelSerializer):
    # Derived fields (server-side)
    base_tax = serializers.SerializerMethodField()
    effective_tax_due = serializers.SerializerMethodField()

    class Meta:
        model = PaymentSchedule
        fields = [
            "id", "purchase_order", "sequence", "label", "basis", "offset_days",
            "percentage", "amount", "currency",
            "due_date", "is_paid", "paid_at", "paid_by", "paid_with_tax",
            # derived:
            "base_tax", "effective_tax_due",
        ]
        read_only_fields = ["paid_at", "paid_by", "currency"]

    def get_base_tax(self, obj):
        vm = self.context.get('vat_map', {})
        item = vm.get('by_id', {}).get(obj.id)
        return item['base_tax'] if item else Decimal('0.00')

    def get_effective_tax_due(self, obj):
        vm = self.context.get('vat_map', {})
        item = vm.get('by_id', {}).get(obj.id)
        return item['effective_tax_due'] if item else Decimal('0.00')


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            'id', 'name', 'contact_person', 'phone', 'address', 'email', 'default_currency', 'default_payment_terms',
            'is_active', 'created_at', 'updated_at', 'default_tax_rate', 'has_dbs', 'dbs_limit', 'dbs_used', 'dbs_currency'
        ]

class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = ['id', 'code', 'name', 'unit']

class PurchaseRequestItemAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequestItemAllocation
        fields = ["id", "job_no", "quantity"]

class PurchaseRequestItemSerializer(serializers.ModelSerializer):
    item = ItemSerializer(read_only=True)
    allocations = PurchaseRequestItemAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequestItem
        fields = [
            'id', 'item', 'quantity', 'priority',
            'specifications', 'order', 'allocations'
        ]

class PurchaseRequestItemAllocationCreateSerializer(serializers.Serializer):
    job_no = serializers.CharField(max_length=20)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)

class PurchaseRequestItemInputSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    priority = serializers.ChoiceField(choices=PurchaseRequest.PRIORITY_CHOICES, required=False)
    specifications = serializers.CharField(required=False, allow_blank=True)
    # New (preferred): split merged line into multiple jobs
    allocations = PurchaseRequestItemAllocationCreateSerializer(many=True, required=False)

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
    payment_terms_name = serializers.ReadOnlyField(source="payment_terms.name")
    
    class Meta:
        model = SupplierOffer
        fields = [
            'id', 'supplier', 'notes', 'item_offers', 'created_at', 'updated_at', 'currency', 'payment_terms', 'payment_terms_name', 'tax_rate'
        ]

class PurchaseRequestSerializer(serializers.ModelSerializer):
    request_items = PurchaseRequestItemSerializer(many=True, read_only=True)
    offers = SupplierOfferSerializer(many=True, read_only=True)
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    status_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    purchase_orders = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    def get_approval(self, obj):
        # if prefetch exists, use it; else fall back to query
        wfs = getattr(obj, "approvals", None)
        wf = None
        if wfs is not None:
            # approvals is a RelatedManager; convert to list or just take first by created_at desc
            wf = next(iter(sorted(wfs.all(), key=lambda w: w.created_at, reverse=True)), None)
        else:
            ct = ContentType.objects.get_for_model(PurchaseRequest)
            wf = ApprovalWorkflow.objects.filter(content_type=ct, object_id=obj.id).order_by("-created_at").first()

        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    def get_status_label(self, obj):
        return obj.get_status_display()
    
    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'request_number', 'title', 'description',
            'requestor', 'requestor_username', 'priority', 'status', 'status_label',
            'total_amount_eur', 'currency_rates_snapshot',
            'created_at', 'updated_at', 'submitted_at',
            'request_items', 'offers', 'approval', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'needed_date', 'purchase_orders'
        ]
        read_only_fields = ['request_number', 'created_at', 'updated_at', 'submitted_at', 'cancelled_at', 'cancelled_by']

# Special serializer for creating purchase requests with nested data
class PurchaseRequestCreateSerializer(serializers.ModelSerializer):
    items = PurchaseRequestItemInputSerializer(many=True, write_only=True)
    suppliers = serializers.ListField(child=serializers.DictField(), write_only=True)
    offers = serializers.DictField(write_only=True)
    recommendations = serializers.DictField(write_only=True)

    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'title', 'description', 'priority',
            'items', 'suppliers', 'offers', 'recommendations', 'total_amount_eur', 'needed_date', 'is_rolling_mill'
        ]
        extra_kwargs = {
            'is_rolling_mill': {'required': False}  # optional, if caller may omit it
        }

    def create(self, validated_data):
        from decimal import Decimal
        items_data = validated_data.pop('items')
        suppliers_data = validated_data.pop('suppliers')
        offers_data = validated_data.pop('offers')
        recommendations_data = validated_data.pop('recommendations')

        # Create PR (needed_date should have a model default to "today")
        pr = PurchaseRequest.objects.create(
            **validated_data,
            requestor=self.context['request'].user,
            status = "submitted",
            submitted_at = timezone.now()
        )

        # Build items
        request_items = []
        for i, item_data in enumerate(items_data):
            # get or create catalog Item
            item, _ = Item.objects.get_or_create(
                code=item_data['code'],
                defaults={'name': item_data['name'], 'unit': item_data['unit']}
            )

            # create merged PR line
            pri = PurchaseRequestItem.objects.create(
                purchase_request=pr,
                item=item,
                quantity=item_data['quantity'],
                priority=item_data.get('priority', 'normal'),
                specifications=item_data.get('specifications', ''),
                order=i
            )
            request_items.append(pri)

            # allocations payload (preferred)
            allocs = item_data.get("allocations") or []

            # Backward‑compat: if no allocations but job_no is provided, create one allocation
            if not allocs and item_data.get("job_no"):
                allocs = [{"job_no": item_data["job_no"], "quantity": item_data["quantity"]}]

            # Validate sum(allocations) == quantity (if allocations present)
            if allocs:
                total_alloc = sum(Decimal(str(a["quantity"])) for a in allocs)
                if total_alloc != Decimal(str(item_data["quantity"])):
                    raise serializers.ValidationError(
                        f"Allocations total ({total_alloc}) != item quantity "
                        f"({item_data['quantity']}) for item code {item.code}."
                    )

                # Create allocation rows
                to_create = [
                    PurchaseRequestItemAllocation(
                        purchase_request_item=pri,
                        job_no=a["job_no"],
                        quantity=a["quantity"]
                    )
                    for a in allocs
                ]
                PurchaseRequestItemAllocation.objects.bulk_create(to_create)

        # Create SupplierOffers + ItemOffers
        for supplier_data in suppliers_data:
            supplier, _ = Supplier.objects.get_or_create(
                name=supplier_data['name'],
                defaults={
                    'contact_person': supplier_data.get('contact_person', ''),
                    'phone': supplier_data.get('phone', ''),
                    'email': supplier_data.get('email', ''),
                    'currency': supplier_data.get('currency', 'TRY'),
                    'default_tax_rate': supplier_data.get('tax_rate', 20)
                }
            )

            # SupplierOffer currency + optional payment_terms (if frontend sends it)
            # Expecting supplier_data.get('payment_terms_code') OR supplier_data.get('payment_terms_id')
            pt = None
            pt_code = supplier_data.get('payment_terms_code')
            pt_id = supplier_data.get('payment_terms_id')
            if pt_id:
                pt = PaymentTerms.objects.filter(id=pt_id, active=True).first()
            elif pt_code:
                pt = PaymentTerms.objects.filter(code=pt_code, active=True).first()

            supplier_offer = SupplierOffer.objects.create(
                purchase_request=pr,
                supplier=supplier,
                currency=supplier_data.get('currency', getattr(supplier, 'default_currency', 'TRY')),
                payment_terms=pt,     # <- capture terms if provided; can be null
                notes=supplier_data.get('notes', ''),
                tax_rate=supplier_data.get('tax_rate', getattr(supplier, 'default_tax_rate', 20))
            )

            # Create item-level offers for this supplier
            bucket = offers_data.get(supplier_data['id']) if 'id' in supplier_data else None
            if bucket:
                for item_index_str, offer_data in bucket.items():
                    item_index = int(item_index_str)
                    if 0 <= item_index < len(request_items):
                        pri = request_items[item_index]
                        is_recommended = (recommendations_data.get(str(item_index)) == supplier_data['id'])
                        ItemOffer.objects.create(
                            purchase_request_item=pri,
                            supplier_offer=supplier_offer,
                            unit_price=offer_data['unitPrice'],
                            total_price=offer_data['totalPrice'],
                            delivery_days=offer_data.get('deliveryDays'),
                            notes=offer_data.get('notes', ''),
                            is_recommended=is_recommended
                        )

        return pr
    
class PurchaseRequestDraftListSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequestDraft
        fields = ['id', 'title', 'description', 'priority', 'needed_date', 'requestor']
        read_only_fields = ['requestor']

class PurchaseRequestDraftDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequestDraft
        fields = ['id', 'title', 'description', 'priority', 'needed_date', 'requestor', 'data']
        read_only_fields = ['requestor']

class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    line_count = serializers.IntegerField(read_only=True)
    status_label = serializers.SerializerMethodField()
    purchase_request_number = serializers.CharField(source='pr.request_number', read_only=True)
    next_unpaid_due = serializers.DateField(read_only=True)

    # nested schedules (read-only) with VAT map
    payment_schedules = serializers.SerializerMethodField()

    # optional PO-level derived
    tax_outstanding = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'pr', 'purchase_request_number', 'supplier', 'supplier_offer', 'supplier_name',
            'currency',
            'total_amount', 'tax_rate', 'total_tax_amount',  # <— persisted fields
            'status', 'priority', 'created_at',
            'line_count', 'status_label',
            'payment_schedules',  # nested with derived fields
            'tax_outstanding', 'next_unpaid_due',    # derived (sum of unpaid effective taxes)
        ]

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_payment_schedules(self, obj):
        vat_map = compute_vat_carry_map(obj)
        ser = PaymentScheduleSerializer(
            obj.payment_schedules.all().order_by('sequence'),
            many=True,
            context={**self.context, 'vat_map': vat_map}
        )
        return ser.data

    def get_tax_outstanding(self, obj):
        return compute_vat_carry_map(obj)['tax_outstanding']

    
class PurchaseOrderLineAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLineAllocation
        fields = ['id', 'job_no', 'quantity', 'amount']

class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source='purchase_request_item.item.code', read_only=True)
    item_name = serializers.CharField(source='purchase_request_item.item.name', read_only=True)
    allocations = PurchaseOrderLineAllocationSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            'id', 'purchase_request_item', 'item_code', 'item_name',
            'quantity', 'unit_price', 'total_price', 'delivery_days', 'notes',
            'allocations',
        ]

class PurchaseOrderDetailSerializer(PurchaseOrderListSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)

    class Meta(PurchaseOrderListSerializer.Meta):
        fields = PurchaseOrderListSerializer.Meta.fields + ['lines']


# Department Request Serializers
class DepartmentRequestSerializer(serializers.ModelSerializer):
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    requestor_full_name = serializers.SerializerMethodField()
    approved_by_username = serializers.ReadOnlyField(source='approved_by.username')
    status_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentRequest
        fields = [
            'id', 'request_number', 'title', 'description', 'department',
            'needed_date', 'items', 'requestor', 'requestor_username', 'requestor_full_name',
            'priority', 'status', 'status_label',
            'approved_by', 'approved_by_username', 'approved_at', 'rejection_reason',
            'created_at', 'submitted_at', 'approval'
        ]
        read_only_fields = [
            'request_number', 'created_at', 'submitted_at',
            'approved_by', 'approved_at',
            # derived from the authenticated user
            'department', 'requestor'
        ]

    def get_requestor_full_name(self, obj):
        if obj.requestor:
            return f"{obj.requestor.first_name} {obj.requestor.last_name}".strip() or obj.requestor.username
        return ""

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_approval(self, obj):
        wfs = getattr(obj, "approvals", None)
        wf = None
        if wfs is not None:
            wf = next(iter(sorted(wfs.all(), key=lambda w: w.created_at, reverse=True)), None)
        else:
            ct = ContentType.objects.get_for_model(DepartmentRequest)
            wf = ApprovalWorkflow.objects.filter(content_type=ct, object_id=obj.id).order_by("-created_at").first()

        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    def create(self, validated_data):
        """
        Create a new department request and automatically submit it for approval.
        """
        from procurement.department_approval_service import submit_department_request

        # Ensure requestor is set to current user
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['requestor'] = request.user
            # Also ensure department matches the user's team
            try:
                team = getattr(getattr(request.user, 'profile', None), 'team', None)
                if team:
                    validated_data['department'] = team
            except Exception:
                # If profile access fails, leave any provided department as-is
                pass

        # Validate items before creation
        items = validated_data.get('items', [])
        if not items:
            raise serializers.ValidationError({"items": "Cannot create request without items."})

        # Create the request object (initially as draft)
        dr = DepartmentRequest.objects.create(**validated_data)

        # Automatically submit for approval
        try:
            submit_department_request(dr, dr.requestor)
        except Exception as e:
            # If submission fails, delete the created request and raise error
            dr.delete()
            raise serializers.ValidationError({"detail": f"Failed to submit request: {str(e)}"})

        return dr
