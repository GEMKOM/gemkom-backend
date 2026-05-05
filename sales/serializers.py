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


class NodeSearchResultSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    breadcrumb = serializers.SerializerMethodField()
    children_count = serializers.IntegerField(source='children.count', read_only=True)

    class Meta:
        model = OfferTemplateNode
        fields = [
            'id', 'code', 'title', 'description',
            'template', 'template_name',
            'breadcrumb', 'children_count', 'is_active',
        ]

    def get_breadcrumb(self, obj):
        """Walk up parent chain to build a title path. Requires select_related on parent chain."""
        parts = []
        node = obj
        while node is not None:
            parts.append(node.title)
            node = node.parent
        parts.reverse()
        return parts


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
    children = serializers.SerializerMethodField()

    class Meta:
        model = SalesOfferItem
        fields = [
            'id', 'offer', 'template_node', 'template_node_detail',
            'quantity', 'title_override', 'notes', 'sequence',
            'unit_price', 'weight_kg', 'delivery_period', 'subtotal',
            'resolved_title', 'parent', 'children', 'created_at',
        ]
        read_only_fields = ['offer', 'created_at']

    def get_children(self, obj):
        return SalesOfferItemSerializer(obj.children.all(), many=True).data


class SalesOfferItemCreateSerializer(serializers.ModelSerializer):
    parent = serializers.PrimaryKeyRelatedField(
        queryset=SalesOfferItem.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = SalesOfferItem
        fields = ['template_node', 'quantity', 'title_override', 'notes', 'sequence', 'unit_price', 'weight_kg', 'delivery_period', 'parent']

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get('template_node') and not attrs.get('title_override'):
                raise serializers.ValidationError(
                    "Either template_node or title_override must be provided."
                )
        parent_item = attrs.get('parent')
        if parent_item is not None:
            offer = self.context.get('offer')
            if offer and parent_item.offer_id != offer.id:
                raise serializers.ValidationError(
                    {'parent': 'Parent item must belong to the same offer.'}
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
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    item_count = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    total_weight_kg = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=''
    )

    class Meta:
        model = SalesOffer
        fields = [
            'id', 'offer_no', 'title', 'status', 'status_display',
            'customer_name',
            'total_price', 'item_count', 'total_weight_kg',
            'created_by_name', 'created_at',
            'delivery_date_requested', 'offer_expiry_date',
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
            'shipping_price', 'pricing_mode',
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
            'pricing_mode',
        ]


class SalesOfferUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOffer
        fields = [
            'customer', 'title', 'description',
            'customer_inquiry_ref', 'delivery_date_requested', 'offer_expiry_date',
            'incoterms', 'delivery_place', 'payment_terms', 'order_no',
            'shipping_price', 'pricing_mode',
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
    notes = serializers.CharField(required=False, allow_blank=True, default='')


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


class SetPricesItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1, required=False)
    weight_kg = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    delivery_period = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class SetPricesSerializer(serializers.Serializer):
    pricing_mode = serializers.ChoiceField(choices=['flat', 'leaf'])
    shipping_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, allow_null=True)
    items = SetPricesItemSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("En az bir kalem girilmelidir.")
        ids = [i['id'] for i in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate item IDs in request.")
        return value


class UpdateItemEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title_override = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(min_value=1, required=False)
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False, allow_null=True)
    weight_kg = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    delivery_period = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    parent = serializers.IntegerField(required=False, allow_null=True)


class BulkUpdateItemsSerializer(serializers.Serializer):
    items = UpdateItemEntrySerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("En az bir kalem girilmelidir.")
        ids = [i['id'] for i in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate item IDs in request.")
        return value


class BulkDeleteItemsSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)

    def validate_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate IDs in request.")
        return value


class UpdateConsultationSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    deadline = serializers.DateField(required=False, allow_null=True)
    file_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_null=True
    )


# =============================================================================
# Approval page serializer — full read for the approver link page
# =============================================================================

class ApprovalPageWorkflowSerializer(serializers.Serializer):
    """
    Per-workflow block for the approver landing page.
    Includes created_at, is_cancelled, snapshot, and policy name
    in addition to what the shared WorkflowSerializer provides.
    """
    policy_name = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    current_stage_order = serializers.IntegerField(read_only=True)
    is_complete = serializers.BooleanField(read_only=True)
    is_rejected = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    snapshot = serializers.JSONField(read_only=True)
    stage_instances = serializers.SerializerMethodField()

    def get_policy_name(self, obj):
        try:
            return obj.policy.name
        except Exception:
            return None

    def get_stage_instances(self, obj):
        from approvals.serializers import StageInstanceSerializer
        from django.contrib.auth.models import User

        stages = list(obj.stage_instances.all().order_by('order'))
        ids = {uid for s in stages for uid in (s.approver_user_ids or [])}
        user_cache = {}
        if ids:
            from approvals.serializers import MiniUserSerializer
            for u in User.objects.filter(id__in=ids).only('id', 'username', 'first_name', 'last_name'):
                user_cache[u.id] = MiniUserSerializer(u).data
        ctx = dict(self.context or {})
        ctx['user_cache'] = user_cache
        return StageInstanceSerializer(stages, many=True, context=ctx).data


class SalesOfferApprovalPageSerializer(serializers.ModelSerializer):
    """
    All-in-one payload for the approver landing page:
    - Offer header info
    - All items (tree)
    - Price history
    - All approval workflows (past + current)
    - current_user_can_decide: whether the requesting user has a pending decision
    """
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    pricing_mode_display = serializers.CharField(source='get_pricing_mode_display', read_only=True)
    payment_terms_detail = PaymentTermsMinimalSerializer(source='payment_terms', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=''
    )
    current_price = SalesOfferCurrentPriceSerializer(read_only=True)
    total_price = serializers.SerializerMethodField()
    total_weight_kg = serializers.SerializerMethodField()

    items = serializers.SerializerMethodField()
    price_history = serializers.SerializerMethodField()
    workflows = serializers.SerializerMethodField()
    current_user_can_decide = serializers.SerializerMethodField()

    class Meta:
        model = SalesOffer
        fields = [
            # header
            'id', 'offer_no', 'title', 'description', 'status', 'status_display',
            'customer', 'customer_name', 'customer_code',
            'customer_inquiry_ref', 'delivery_date_requested', 'offer_expiry_date',
            'incoterms', 'delivery_place',
            'payment_terms', 'payment_terms_detail',
            'order_no', 'shipping_price',
            'pricing_mode', 'pricing_mode_display',
            'approval_round',
            'current_price', 'total_price', 'total_weight_kg',
            'created_by', 'created_by_name', 'created_at', 'updated_at',
            # related
            'items',
            'price_history',
            'workflows',
            'current_user_can_decide',
        ]

    def get_total_price(self, obj):
        return obj.total_price

    def get_total_weight_kg(self, obj):
        return obj.total_weight_kg

    def get_items(self, obj):
        roots = obj.items.filter(parent__isnull=True).order_by('sequence')
        return SalesOfferItemSerializer(roots, many=True).data

    def get_price_history(self, obj):
        revisions = obj.price_revisions.order_by('created_at')
        return SalesOfferPriceRevisionSerializer(revisions, many=True).data

    def get_workflows(self, obj):
        from django.contrib.contenttypes.models import ContentType
        from approvals.models import ApprovalWorkflow

        ct = ContentType.objects.get_for_model(SalesOffer)
        workflows = (
            ApprovalWorkflow.objects
            .filter(content_type=ct, object_id=obj.id)
            .prefetch_related('stage_instances__decisions__approver')
            .select_related('policy')
            .order_by('created_at')
        )
        return ApprovalPageWorkflowSerializer(
            workflows, many=True, context=self.context
        ).data

    def get_current_user_can_decide(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        if obj.status != 'pending_approval':
            return False

        from django.contrib.contenttypes.models import ContentType
        from approvals.models import ApprovalWorkflow, ApprovalDecision

        ct = ContentType.objects.get_for_model(SalesOffer)
        wf = (
            ApprovalWorkflow.objects
            .filter(content_type=ct, object_id=obj.id, is_complete=False, is_rejected=False, is_cancelled=False)
            .prefetch_related('stage_instances')
            .order_by('-created_at')
            .first()
        )
        if not wf:
            return False

        current_stage = wf.stage_instances.filter(order=wf.current_stage_order).first()
        if not current_stage:
            return False

        user_id = request.user.id
        if user_id not in (current_stage.approver_user_ids or []):
            return False

        already_decided = ApprovalDecision.objects.filter(
            stage_instance=current_stage,
            approver=request.user,
        ).exists()
        return not already_decided
