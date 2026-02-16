from procurement.services import compute_vat_carry_map
from rest_framework import serializers
from django.utils import timezone

from approvals.serializers import WorkflowSerializer
from .models import (
    PaymentSchedule, PaymentTerms, PurchaseOrder, PurchaseOrderLine, PurchaseOrderLineAllocation,
    PurchaseRequestDraft, PurchaseRequestItemAllocation, Supplier, Item, PurchaseRequest,
    PurchaseRequestItem, SupplierOffer, ItemOffer
)
from decimal import Decimal
from django.db import models

from django.contrib.contenttypes.models import ContentType

from approvals.models import ApprovalWorkflow
from planning.serializers import FileAttachmentSerializer

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
    unit_label = serializers.CharField(source='get_unit_display', read_only=True)
    item_type_label = serializers.CharField(source='get_item_type_display', read_only=True)

    class Meta:
        model = Item
        fields = ['id', 'code', 'name', 'unit', 'unit_label', 'item_type', 'item_type_label', 'stock_quantity']

class PurchaseRequestItemAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseRequestItemAllocation
        fields = ["id", "job_no", "quantity"]

class PurchaseRequestItemSerializer(serializers.ModelSerializer):
    item = ItemSerializer(read_only=True)
    allocations = PurchaseRequestItemAllocationSerializer(many=True, read_only=True)
    files = FileAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequestItem
        fields = [
            'id', 'item', 'quantity', 'item_description', 'priority',
            'specifications', 'order', 'allocations', 'files'
        ]

class PurchaseRequestItemAllocationCreateSerializer(serializers.Serializer):
    job_no = serializers.CharField(max_length=20)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)

class PurchaseRequestItemInputSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    unit = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    item_description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=PurchaseRequest.PRIORITY_CHOICES, required=False)
    specifications = serializers.CharField(required=False, allow_blank=True)
    # New (preferred): split merged line into multiple jobs
    allocations = PurchaseRequestItemAllocationCreateSerializer(many=True, required=False)
    # FileAsset IDs to attach to this item
    file_asset_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        help_text="List of FileAsset IDs to attach to this purchase request item"
    )
    # Link to source planning request item for progress tracking
    planning_request_item_id = serializers.IntegerField(required=False, allow_null=True)

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

class PurchaseRequestListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views - excludes nested items, offers, approval workflow"""
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    status_label = serializers.SerializerMethodField()
    items_count = serializers.IntegerField(read_only=True)
    planning_request_keys = serializers.SerializerMethodField()
    purchase_orders = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    item_type = serializers.SerializerMethodField()
    item_type_label = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'request_number', 'title', 'description',
            'requestor', 'requestor_username', 'priority', 'status', 'status_label',
            'total_amount_eur', 'currency_rates_snapshot',
            'created_at', 'updated_at', 'submitted_at',
            'items_count', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'needed_date',
            'planning_request_keys', 'purchase_orders', 'item_type', 'item_type_label'
        ]
        read_only_fields = ['request_number', 'created_at', 'updated_at', 'submitted_at', 'cancelled_at', 'cancelled_by']

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_item_type(self, obj):
        """Get the item_type from the first request item"""
        first_item = obj.request_items.order_by('order').first()
        if first_item and first_item.item:
            return first_item.item.item_type
        return None

    def get_item_type_label(self, obj):
        """Get the item_type display label from the first request item"""
        first_item = obj.request_items.order_by('order').first()
        if first_item and first_item.item:
            return first_item.item.get_item_type_display()
        return None

    def get_planning_request_keys(self, obj):
        """Get unique planning request numbers (cheap with prefetch_related)"""
        planning_request_items = obj.planning_request_items.all()

        # Get unique planning requests
        planning_requests = {}
        for pri_item in planning_request_items:
            pr = pri_item.planning_request
            if pr.id not in planning_requests:
                planning_requests[pr.id] = pr.request_number

        return sorted(list(planning_requests.values()))


class PurchaseRequestSerializer(serializers.ModelSerializer):
    """Full serializer for detail views - includes nested items, offers, approval workflow"""
    request_items = PurchaseRequestItemSerializer(many=True, read_only=True)
    offers = SupplierOfferSerializer(many=True, read_only=True)
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    status_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    purchase_orders = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    planning_request_info = serializers.SerializerMethodField()
    files = FileAttachmentSerializer(many=True, read_only=True)

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

    def get_planning_request_info(self, obj):
        """Get unique planning requests that this PR was created from"""
        # Get all planning request items linked to this PR
        planning_request_items = obj.planning_request_items.select_related('planning_request').all()

        # Get unique planning requests
        planning_requests = {}
        for pri_item in planning_request_items:
            pr = pri_item.planning_request
            if pr.id not in planning_requests:
                planning_requests[pr.id] = {
                    'id': pr.id,
                    'request_number': pr.request_number,
                    'title': pr.title
                }

        return list(planning_requests.values())

    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'request_number', 'title', 'description',
            'requestor', 'requestor_username', 'priority', 'status', 'status_label',
            'total_amount_eur', 'currency_rates_snapshot',
            'created_at', 'updated_at', 'submitted_at',
            'request_items', 'offers', 'approval', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'needed_date', 'purchase_orders',
            'planning_request_info', 'files'
        ]
        read_only_fields = ['request_number', 'created_at', 'updated_at', 'submitted_at', 'cancelled_at', 'cancelled_by']


# Special serializer for creating purchase requests with nested data
class PurchaseRequestCreateSerializer(serializers.ModelSerializer):
    items = PurchaseRequestItemInputSerializer(many=True, write_only=True)
    suppliers = serializers.ListField(child=serializers.DictField(), write_only=True)
    offers = serializers.DictField(write_only=True)
    recommendations = serializers.DictField(write_only=True)
    planning_request_item_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="List of PlanningRequestItem IDs to link to this purchase request"
    )

    def validate_planning_request_item_ids(self, value):
        """
        Validate that planning request items have remaining quantity available for purchase.
        Supports partial conversion: an item can be split across multiple purchase requests
        as long as the total doesn't exceed quantity_to_purchase.
        """
        if not value:
            return value

        from planning.models import PlanningRequestItem

        # Get the items
        items = PlanningRequestItem.objects.filter(id__in=value).select_related(
            'item', 'planning_request'
        )

        # Check each item has remaining quantity
        unavailable_items = []
        for item in items:
            if not item.is_available_for_purchase:
                unavailable_items.append({
                    'item_id': item.id,
                    'item_code': item.item.code,
                    'item_name': item.item.name,
                    'job_no': item.job_no,
                    'planning_request': item.planning_request.request_number,
                    'quantity_to_purchase': item.quantity_to_purchase,
                    'quantity_in_active_prs': item.quantity_in_active_prs,
                })

        if unavailable_items:
            error_details = []
            for item in unavailable_items:
                error_details.append(
                    f"Item '{item['item_code']} - {item['item_name']}' (Job: {item['job_no']}) from {item['planning_request']} "
                    f"has no remaining quantity (to_purchase: {item['quantity_to_purchase']}, already in PRs: {item['quantity_in_active_prs']})"
                )

            error_message = [
                "Some planning request items have no remaining quantity available:",
                *error_details,
                "Note: Items become available again if their purchase request is rejected or cancelled."
            ]
            raise serializers.ValidationError(error_message)

        return value

    class Meta:
        model = PurchaseRequest
        fields = [
            'id', 'title', 'description', 'priority',
            'items', 'suppliers', 'offers', 'recommendations', 'total_amount_eur', 'needed_date', 'is_rolling_mill',
            'planning_request_item_ids'
        ]
        extra_kwargs = {
            'is_rolling_mill': {'required': False}  # optional, if caller may omit it
        }

    def create(self, validated_data):
        from decimal import Decimal
        from planning.models import PlanningRequestItem, FileAsset, FileAttachment

        items_data = validated_data.pop('items')
        suppliers_data = validated_data.pop('suppliers')
        offers_data = validated_data.pop('offers')
        recommendations_data = validated_data.pop('recommendations')
        planning_request_item_ids = validated_data.pop('planning_request_item_ids', [])

        # Create PR (needed_date should have a model default to "today")
        pr = PurchaseRequest.objects.create(
            **validated_data,
            requestor=self.context['request'].user,
            status = "submitted",
            submitted_at = timezone.now()
        )

        # Attach planning request items if provided
        user = self.context['request'].user
        ct_pr = ContentType.objects.get_for_model(PurchaseRequest)

        if planning_request_item_ids:
            from django.db.models import Q

            planning_request_items = PlanningRequestItem.objects.filter(
                Q(planning_request__status='ready') | Q(planning_request__status='converted'),
                id__in=planning_request_item_ids
            ).select_related('planning_request').prefetch_related('planning_request__files')

            # Attach items to purchase request
            pr.planning_request_items.set(planning_request_items)

            # Get unique planning requests and mark them as 'converted'
            # Also copy PlanningRequest-level files to PurchaseRequest
            planning_requests = set(item.planning_request for item in planning_request_items)
            copied_asset_ids = set()  # Track copied assets to avoid duplicates
            for planning_request in planning_requests:
                # Copy files from PlanningRequest to PurchaseRequest
                for source_attachment in planning_request.files.all():
                    if source_attachment.asset_id not in copied_asset_ids:
                        FileAttachment.objects.create(
                            asset=source_attachment.asset,
                            uploaded_by=user,
                            description=source_attachment.description,
                            content_type=ct_pr,
                            object_id=pr.id,
                            source_attachment=source_attachment,
                        )
                        copied_asset_ids.add(source_attachment.asset_id)

                # Check completion stats
                stats = planning_request.get_completion_stats()

                # Mark as 'converted' if any items are now in at least one purchase request
                # Do NOT mark as 'completed' here - that happens when PR is approved
                if stats['converted_items'] > 0 and planning_request.status == 'ready':
                    planning_request.status = 'converted'
                    planning_request.converted_at = timezone.now()
                    planning_request.save(update_fields=['status', 'converted_at'])

        # Build items
        request_items = []
        for i, item_data in enumerate(items_data):
            # get or create catalog Item
            item, _ = Item.objects.get_or_create(
                code=item_data['code'],
                defaults={'name': item_data['name'], 'unit': item_data['unit']}
            )

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

            # Get planning request item if provided
            planning_request_item = None
            planning_request_item_id = item_data.get('planning_request_item_id')
            if planning_request_item_id:
                from planning.models import PlanningRequestItem
                try:
                    planning_request_item = PlanningRequestItem.objects.get(id=planning_request_item_id)
                except PlanningRequestItem.DoesNotExist:
                    pass

            # create merged PR line
            pri = PurchaseRequestItem.objects.create(
                purchase_request=pr,
                item=item,
                quantity=item_data['quantity'],
                item_description=item_data.get('item_description', ''),
                priority=item_data.get('priority', 'normal'),
                specifications=item_data.get('specifications', ''),
                order=i,
                planning_request_item=planning_request_item
            )
            request_items.append(pri)

            # Create allocation rows
            if allocs:
                to_create = [
                    PurchaseRequestItemAllocation(
                        purchase_request_item=pri,
                        job_no=a["job_no"],
                        quantity=a["quantity"]
                    )
                    for a in allocs
                ]
                PurchaseRequestItemAllocation.objects.bulk_create(to_create)

            # Create file attachments for this purchase request item
            user = self.context['request'].user
            ct_item = ContentType.objects.get_for_model(PurchaseRequestItem)

            # First, copy files from PlanningRequestItem if available
            if planning_request_item:
                for source_attachment in planning_request_item.files.all():
                    FileAttachment.objects.create(
                        asset=source_attachment.asset,
                        uploaded_by=user,
                        description=source_attachment.description,
                        content_type=ct_item,
                        object_id=pri.id,
                        source_attachment=source_attachment,
                    )

            # Then, add any additional file assets explicitly provided
            file_asset_ids = item_data.get('file_asset_ids', [])
            if file_asset_ids:
                file_assets = FileAsset.objects.filter(id__in=file_asset_ids)
                for asset in file_assets:
                    FileAttachment.objects.create(
                        asset=asset,
                        uploaded_by=user,
                        description='',
                        content_type=ct_item,
                        object_id=pri.id,
                    )

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
            'id', 'purchase_request_item', 'item_code', 'item_name', 'item_description',
            'quantity', 'unit_price', 'total_price', 'delivery_days', 'notes',
            'is_delivered', 'delivered_at',
            'allocations',
        ]

class PurchaseOrderDetailSerializer(PurchaseOrderListSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)

    class Meta(PurchaseOrderListSerializer.Meta):
        fields = PurchaseOrderListSerializer.Meta.fields + ['lines']
