from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from approvals.models import ApprovalWorkflow
from approvals.serializers import WorkflowSerializer
from planning.serializers import (
    AttachmentUploadSerializer,
    FileAttachmentSerializer,
    validate_job_no_not_phased,
)
from users.helpers import get_dept_code_for_user

from .models import PROCUREMENT_ITEM_CODE, CraneRate, CraneRequest, CraneType
from .services import FACTORY_JOB_NO, user_can_complete


class CraneRateSerializer(serializers.ModelSerializer):
    created_by_username = serializers.ReadOnlyField(source='created_by.username')

    class Meta:
        model = CraneRate
        fields = [
            'id', 'crane_type', 'effective_from', 'currency',
            'price_up_to_3h', 'price_up_to_8h', 'price_per_day',
            'transport_fee', 'rigger_fee', 'note',
            'created_at', 'created_by', 'created_by_username',
        ]
        read_only_fields = ['created_at', 'created_by']


class CraneTypeSerializer(serializers.ModelSerializer):
    category_label = serializers.SerializerMethodField()
    is_platform = serializers.ReadOnlyField()
    current_rate = serializers.SerializerMethodField()

    class Meta:
        model = CraneType
        fields = [
            'id', 'name', 'category', 'category_label', 'is_platform',
            'is_active', 'sort_order', 'current_rate',
        ]

    def get_category_label(self, obj):
        return obj.get_category_display()

    def get_current_rate(self, obj):
        # Prefer the prefetched rates (ordered -effective_from) to avoid N+1.
        rates = getattr(obj, '_prefetched_objects_cache', {}).get('rates')
        if rates is not None:
            from django.utils import timezone
            today = timezone.localdate()
            rate = next((r for r in rates if r.effective_from <= today), None)
        else:
            rate = obj.current_rate()
        if not rate:
            return None
        return CraneRateSerializer(rate).data


class CraneRequestListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    requestor_full_name = serializers.SerializerMethodField()
    approved_by_username = serializers.ReadOnlyField(source='approved_by.username')
    completed_by_username = serializers.ReadOnlyField(source='completed_by.username')
    crane_type_name = serializers.ReadOnlyField(source='crane_type.name')
    crane_type_category = serializers.ReadOnlyField(source='crane_type.category')
    status_label = serializers.SerializerMethodField()
    pricing_option_label = serializers.SerializerMethodField()

    class Meta:
        model = CraneRequest
        fields = [
            'id', 'request_number', 'department', 'job_no',
            'crane_type', 'crane_type_name', 'crane_type_category',
            'pricing_option', 'pricing_option_label', 'days', 'needs_rigger',
            'needed_date', 'needed_time', 'location',
            'requestor', 'requestor_username', 'requestor_full_name',
            'priority', 'status', 'status_label',
            'estimated_cost', 'estimated_cost_currency',
            'actual_quantity', 'actual_cost', 'actual_cost_currency',
            'approved_by', 'approved_by_username', 'approved_at',
            'completed_by', 'completed_by_username', 'completed_at',
            'rejection_reason', 'created_at', 'submitted_at',
        ]
        read_only_fields = fields

    def get_requestor_full_name(self, obj):
        if obj.requestor:
            return f"{obj.requestor.first_name} {obj.requestor.last_name}".strip() or obj.requestor.username
        return ""

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_pricing_option_label(self, obj):
        return obj.get_pricing_option_display()


class CraneRequestSerializer(serializers.ModelSerializer):
    """Full serializer for detail views + create."""
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    requestor_full_name = serializers.SerializerMethodField()
    approved_by_username = serializers.ReadOnlyField(source='approved_by.username')
    completed_by_username = serializers.ReadOnlyField(source='completed_by.username')
    crane_type_name = serializers.ReadOnlyField(source='crane_type.name')
    crane_type_category = serializers.ReadOnlyField(source='crane_type.category')
    status_label = serializers.SerializerMethodField()
    pricing_option_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    files = FileAttachmentSerializer(many=True, read_only=True)
    attachments = AttachmentUploadSerializer(many=True, write_only=True, required=False)
    procurement_item_code = serializers.SerializerMethodField()
    can_complete = serializers.SerializerMethodField()

    class Meta:
        model = CraneRequest
        fields = [
            'id', 'request_number', 'department', 'job_no',
            'crane_type', 'crane_type_name', 'crane_type_category',
            'pricing_option', 'pricing_option_label', 'days', 'needs_rigger',
            'needed_date', 'needed_time', 'location', 'description',
            'requestor', 'requestor_username', 'requestor_full_name',
            'priority', 'status', 'status_label',
            'estimated_cost', 'estimated_cost_currency', 'estimate_breakdown',
            'actual_quantity', 'actual_cost', 'actual_cost_currency',
            'approved_by', 'approved_by_username', 'approved_at',
            'completed_by', 'completed_by_username', 'completed_at',
            'rejection_reason', 'created_at', 'submitted_at',
            'approval', 'files', 'attachments',
            'procurement_item_code', 'can_complete',
        ]
        read_only_fields = [
            'request_number', 'department', 'requestor', 'status',
            'estimated_cost', 'estimated_cost_currency', 'estimate_breakdown',
            'actual_quantity', 'actual_cost', 'actual_cost_currency',
            'approved_by', 'approved_at', 'completed_by', 'completed_at',
            'rejection_reason', 'created_at', 'submitted_at',
        ]

    def get_requestor_full_name(self, obj):
        if obj.requestor:
            return f"{obj.requestor.first_name} {obj.requestor.last_name}".strip() or obj.requestor.username
        return ""

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_pricing_option_label(self, obj):
        return obj.get_pricing_option_display()

    def get_procurement_item_code(self, obj):
        return PROCUREMENT_ITEM_CODE

    def get_can_complete(self, obj):
        # True also for completed requests: coordinators may correct actuals.
        request = self.context.get('request')
        if not request or obj.status not in ('approved', 'completed'):
            return False
        return user_can_complete(request.user)

    def get_approval(self, obj):
        wfs = getattr(obj, "approvals", None)
        wf = None
        if wfs is not None:
            wf = next(iter(sorted(wfs.all(), key=lambda w: w.created_at, reverse=True)), None)
        else:
            ct = ContentType.objects.get_for_model(CraneRequest)
            wf = ApprovalWorkflow.objects.filter(content_type=ct, object_id=obj.id).order_by("-created_at").first()

        if not wf:
            return None
        return WorkflowSerializer(wf, context=self.context).data

    def validate_job_no(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError("İş emri numarası zorunludur.")
        if value != FACTORY_JOB_NO:
            from projects.models import JobOrder
            if not JobOrder.objects.filter(job_no=value).exists():
                raise serializers.ValidationError(f"'{value}' numaralı iş emri bulunamadı.")
        return validate_job_no_not_phased(value)

    def validate(self, attrs):
        if attrs.get('pricing_option') == 'daily':
            days = attrs.get('days') or 1
            if days < 1:
                raise serializers.ValidationError({"days": "Gün sayısı en az 1 olmalıdır."})
        return attrs

    def create(self, validated_data):
        """Create a new crane request and automatically submit it for approval."""
        from django.core.exceptions import ValidationError as DjangoValidationError
        from django.db import transaction

        from planning.services import create_dr_file_assets_from_uploads

        from .services import compute_estimate, submit_crane_request

        validated_data.pop('attachments', None)

        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['requestor'] = request.user
            try:
                team = get_dept_code_for_user(request.user)
                if team:
                    validated_data['department'] = team
            except Exception:
                pass
        validated_data.setdefault('department', 'other')

        # Cost estimate snapshot (server-side authority)
        try:
            total, currency, breakdown = compute_estimate(
                validated_data['crane_type'],
                validated_data['pricing_option'],
                days=validated_data.get('days') or 1,
                needs_rigger=validated_data.get('needs_rigger', False),
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError({"pricing_option": e.messages})

        validated_data['estimated_cost'] = total
        validated_data['estimated_cost_currency'] = currency
        validated_data['estimate_breakdown'] = breakdown

        uploaded_files = []
        if request and hasattr(request, 'FILES'):
            uploaded_files = request.FILES.getlist('files')

        with transaction.atomic():
            cr = CraneRequest.objects.create(**validated_data)
            create_dr_file_assets_from_uploads(cr, request.user, uploaded_files)
            submit_crane_request(cr, cr.requestor)
            return cr
