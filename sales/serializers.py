from rest_framework import serializers

from projects.models import Customer
from procurement.models import PaymentTerms

from .models import (
    OfferTemplate,
    OfferTemplateNode,
    SalesOffer,
    SalesOfferItem,
    SalesOfferFile,
    SalesOfferPriceRevision,
)


# =============================================================================
# Shared
# =============================================================================

class PaymentTermsMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerms
        fields = ['id', 'name', 'code']


# =============================================================================
# Catalog serializers
# =============================================================================

class OfferTemplateNodeSerializer(serializers.ModelSerializer):
    """Flat node serializer — children are loaded on demand."""
    children_count = serializers.IntegerField(source='children.count', read_only=True)

    class Meta:
        model = OfferTemplateNode
        fields = [
            'id', 'template', 'parent', 'title', 'description',
            'sequence', 'is_active', 'children_count',
        ]


class OfferTemplateNodeCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferTemplateNode
        fields = ['id', 'template', 'parent', 'title', 'description', 'sequence', 'is_active']
        read_only_fields = ['template']


class OfferTemplateListSerializer(serializers.ModelSerializer):
    node_count = serializers.SerializerMethodField()

    class Meta:
        model = OfferTemplate
        fields = ['id', 'name', 'description', 'is_active', 'node_count', 'created_at']

    def get_node_count(self, obj):
        return obj.nodes.filter(is_active=True).count()


class OfferTemplateDetailSerializer(serializers.ModelSerializer):
    root_nodes = serializers.SerializerMethodField()

    class Meta:
        model = OfferTemplate
        fields = [
            'id', 'name', 'description', 'is_active',
            'root_nodes', 'created_by', 'created_at', 'updated_at',
        ]

    def get_root_nodes(self, obj):
        roots = obj.nodes.filter(parent__isnull=True, is_active=True).order_by('sequence')
        return OfferTemplateNodeSerializer(roots, many=True).data


class OfferTemplateCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OfferTemplate
        fields = ['id', 'name', 'description', 'is_active']


# =============================================================================
# File serializers
# =============================================================================

class SalesOfferFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_type_display = serializers.CharField(source='get_file_type_display', read_only=True)
    filename = serializers.CharField(read_only=True)
    file_size = serializers.IntegerField(read_only=True)
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.get_full_name', read_only=True, default=''
    )

    class Meta:
        model = SalesOfferFile
        fields = [
            'id', 'offer', 'file', 'file_url', 'filename', 'file_size',
            'file_type', 'file_type_display',
            'name', 'description',
            'uploaded_at', 'uploaded_by', 'uploaded_by_name',
        ]
        read_only_fields = ['uploaded_at', 'uploaded_by', 'offer']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class SalesOfferFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOfferFile
        fields = ['file', 'file_type', 'name', 'description']


# =============================================================================
# Price revision serializers
# =============================================================================

class SalesOfferPriceRevisionSerializer(serializers.ModelSerializer):
    revision_type_display = serializers.CharField(
        source='get_revision_type_display', read_only=True
    )
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=''
    )

    class Meta:
        model = SalesOfferPriceRevision
        fields = [
            'id', 'offer', 'revision_type', 'revision_type_display',
            'amount', 'currency', 'currency_display',
            'approval_round',
            'counter_amount', 'counter_currency',
            'notes', 'is_current',
            'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = [
            'offer', 'revision_type', 'approval_round', 'is_current',
            'created_by', 'created_at',
        ]


# =============================================================================
# Item serializers
# =============================================================================

class SalesOfferItemNodeSummarySerializer(serializers.ModelSerializer):
    """Lightweight node summary embedded in item."""
    class Meta:
        model = OfferTemplateNode
        fields = ['id', 'title', 'description', 'sequence']


class SalesOfferItemSerializer(serializers.ModelSerializer):
    template_node_detail = SalesOfferItemNodeSummarySerializer(
        source='template_node', read_only=True
    )
    resolved_title = serializers.CharField(read_only=True)
    subtotal = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = SalesOfferItem
        fields = [
            'id', 'offer', 'template_node', 'template_node_detail',
            'quantity', 'title_override', 'notes', 'sequence',
            'unit_price', 'weight_kg', 'delivery_period', 'subtotal',
            'resolved_title', 'created_at',
        ]
        read_only_fields = ['offer', 'created_at']


class SalesOfferItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOfferItem
        fields = ['template_node', 'quantity', 'title_override', 'notes', 'sequence', 'unit_price', 'weight_kg', 'delivery_period']

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get('template_node') and not attrs.get('title_override'):
                raise serializers.ValidationError(
                    "Either template_node or title_override must be provided."
                )
        return attrs


# =============================================================================
# Main offer serializers
# =============================================================================

class SalesOfferCurrentPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOfferPriceRevision
        fields = ['id', 'amount', 'currency', 'revision_type', 'approval_round']


class SalesOfferListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    current_price = SalesOfferCurrentPriceSerializer(read_only=True)
    item_count = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    total_weight_kg = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=''
    )
    payment_terms_detail = PaymentTermsMinimalSerializer(source='payment_terms', read_only=True)
    needs_my_approval = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = SalesOffer
        fields = [
            'id', 'offer_no', 'title', 'status', 'status_display',
            'customer', 'customer_name', 'customer_code',
            'delivery_date_requested', 'offer_expiry_date',
            'delivery_place', 'payment_terms', 'payment_terms_detail', 'order_no',
            'shipping_price',
            'current_price', 'item_count',
            'total_price', 'total_weight_kg',
            'approval_round',
            'needs_my_approval',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]

    def get_item_count(self, obj):
        return obj.items.count()

    def get_total_price(self, obj):
        return obj.total_price

    def get_total_weight_kg(self, obj):
        return obj.total_weight_kg


class SalesOfferJobOrderSummarySerializer(serializers.Serializer):
    job_no = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    parent = serializers.CharField(allow_null=True)


class SalesOfferDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    current_price = SalesOfferCurrentPriceSerializer(read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=''
    )
    converted_job_order_no = serializers.CharField(
        source='converted_job_order.job_no', read_only=True, default=None
    )
    job_orders = SalesOfferJobOrderSummarySerializer(many=True, read_only=True)
    total_price = serializers.SerializerMethodField()
    total_weight_kg = serializers.SerializerMethodField()
    payment_terms_detail = PaymentTermsMinimalSerializer(source='payment_terms', read_only=True)

    class Meta:
        model = SalesOffer
        fields = [
            'id', 'offer_no', 'title', 'description',
            'status', 'status_display',
            'customer', 'customer_name', 'customer_code',
            'customer_inquiry_ref', 'delivery_date_requested', 'offer_expiry_date',
            'incoterms', 'delivery_place', 'payment_terms', 'payment_terms_detail', 'order_no',
            'shipping_price',
            'approval_round',
            'current_price',
            'total_price', 'total_weight_kg',
            'converted_job_order', 'converted_job_order_no',
            'job_orders',
            'submitted_to_customer_at', 'won_at', 'lost_at', 'cancelled_at',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]

    def get_total_price(self, obj):
        return obj.total_price

    def get_total_weight_kg(self, obj):
        return obj.total_weight_kg


class SalesOfferCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOffer
        fields = [
            'customer', 'title', 'description',
            'customer_inquiry_ref', 'delivery_date_requested', 'offer_expiry_date',
            'incoterms', 'delivery_place', 'payment_terms', 'order_no',
        ]


class SalesOfferUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOffer
        fields = [
            'customer', 'title', 'description',
            'customer_inquiry_ref', 'delivery_date_requested', 'offer_expiry_date',
            'incoterms', 'delivery_place', 'payment_terms', 'order_no',
        ]

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.converted_job_order_id:
            raise serializers.ValidationError(
                "İş emrine dönüştürülmüş teklifler güncellenemez."
            )
        return attrs


# =============================================================================
# Action serializers
# =============================================================================

class SendConsultationDeptSerializer(serializers.Serializer):
    department = serializers.ChoiceField(choices=[
        'design', 'planning', 'procurement', 'manufacturing', 'painting', 'logistics'
    ])
    assigned_to = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    deadline = serializers.DateField(required=False, allow_null=True)
    file_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )


class SendConsultationsSerializer(serializers.Serializer):
    departments = SendConsultationDeptSerializer(many=True)

    def validate_departments(self, value):
        if not value:
            raise serializers.ValidationError("En az bir departman seçilmelidir.")
        return value


class SubmitForApprovalSerializer(serializers.Serializer):
    pass  # No fields needed — policy is auto-selected by name on the backend


class RecordApprovalDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    comment = serializers.CharField(required=False, allow_blank=True, default='')
    counter_amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, required=False, allow_null=True
    )
    counter_currency = serializers.ChoiceField(
        choices=['TRY', 'USD', 'EUR', 'GBP'],
        required=False,
        default='EUR'
    )


class AddItemsSerializer(serializers.Serializer):
    items = SalesOfferItemCreateSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("En az bir kalem girilmelidir.")
        return value


class UpdateConsultationSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    deadline = serializers.DateField(required=False, allow_null=True)
    file_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )
