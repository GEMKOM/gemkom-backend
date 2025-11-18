from rest_framework import serializers
from django.db import models as django_models
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal

from .models import DepartmentRequest, PlanningRequest, PlanningRequestItem, FileAsset, FileAttachment
from procurement.models import Item
from approvals.serializers import WorkflowSerializer
from approvals.models import ApprovalWorkflow


class AttachmentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)
    source_attachment_id = serializers.IntegerField(required=False)


class FileAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_name = serializers.SerializerMethodField()
    asset_id = serializers.PrimaryKeyRelatedField(source='asset', read_only=True)

    class Meta:
        model = FileAttachment
        fields = [
            'id', 'asset_id', 'file_url', 'file_name',
            'description', 'uploaded_at', 'uploaded_by', 'source_attachment'
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        request = self.context.get('request')
        url = obj.asset.file.url if obj.asset and obj.asset.file else ''
        return request.build_absolute_uri(url) if request else url

    def get_file_name(self, obj):
        if obj.asset and obj.asset.file:
            return obj.asset.file.name.split('/')[-1]
        return ''


# Department Request Serializers
class DepartmentRequestSerializer(serializers.ModelSerializer):
    requestor_username = serializers.ReadOnlyField(source='requestor.username')
    requestor_full_name = serializers.SerializerMethodField()
    approved_by_username = serializers.ReadOnlyField(source='approved_by.username')
    status_label = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    files = FileAttachmentSerializer(many=True, read_only=True)
    attachments = AttachmentUploadSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = DepartmentRequest
        fields = [
            'id', 'request_number', 'title', 'description', 'department',
            'needed_date', 'items', 'requestor', 'requestor_username', 'requestor_full_name',
            'priority', 'status', 'status_label',
            'approved_by', 'approved_by_username', 'approved_at', 'rejection_reason',
            'created_at', 'submitted_at', 'approval',
            'files', 'attachments'
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
        from planning.services import submit_department_request

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

        attachments_data = validated_data.pop('attachments', [])

        # Create the request object (initially as draft)
        dr = DepartmentRequest.objects.create(**validated_data)

        # Create the request object (initially as draft)
        if attachments_data:
            self._create_attachments(dr, attachments_data, request.user if request else None)

        # Automatically submit for approval
        try:
            submit_department_request(dr, dr.requestor)
        except Exception as e:
            # If submission fails, delete the created request and raise error
            dr.delete()
            raise serializers.ValidationError({"detail": f"Failed to submit request: {str(e)}"})

        return dr

    def _create_attachments(self, obj, attachments_data, user):
        ct = ContentType.objects.get_for_model(obj)
        for att in attachments_data:
            source_attachment = None
            source_id = att.get('source_attachment_id')
            if source_id:
                try:
                    source_attachment = FileAttachment.objects.get(id=source_id)
                except FileAttachment.DoesNotExist:
                    raise serializers.ValidationError({"attachments": f"source_attachment_id {source_id} not found"})
            asset = FileAsset.objects.create(
                file=att['file'],
                uploaded_by=user,
                description=att.get('description', '')
            )
            FileAttachment.objects.create(
                asset=asset,
                uploaded_by=user,
                description=att.get('description', ''),
                source_attachment=source_attachment,
                content_type=ct,
                object_id=obj.id,
            )


# Planning Request Serializers
class PlanningRequestItemSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source='item.code', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_unit = serializers.CharField(source='item.unit', read_only=True)
    files = FileAttachmentSerializer(many=True, read_only=True)
    attachments = AttachmentUploadSerializer(many=True, write_only=True, required=False)

    # For write operations
    item_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = PlanningRequestItem
        fields = [
            'id', 'item', 'item_id', 'item_code', 'item_name', 'item_unit',
            'job_no', 'quantity', 'priority', 'specifications',
            'source_item_index', 'order', 'files', 'attachments'
        ]
        read_only_fields = ['id']


class PlanningRequestSerializer(serializers.ModelSerializer):
    items = PlanningRequestItemSerializer(many=True, read_only=True)
    created_by_username = serializers.ReadOnlyField(source='created_by.username')
    created_by_full_name = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    department_request_number = serializers.CharField(source='department_request.request_number', read_only=True)
    purchase_request_number = serializers.CharField(source='purchase_request.request_number', read_only=True)
    files = FileAttachmentSerializer(many=True, read_only=True)
    department_files = FileAttachmentSerializer(many=True, read_only=True, source='department_request.files')

    class Meta:
        model = PlanningRequest
        fields = [
            'id', 'request_number', 'title', 'description', 'needed_date',
            'department_request', 'department_request_number',
            'created_by', 'created_by_username', 'created_by_full_name',
            'priority', 'status', 'status_label',
            'created_at', 'updated_at', 'ready_at', 'converted_at',
            'purchase_request', 'purchase_request_number',
            'items', 'files', 'department_files'
        ]
        read_only_fields = [
            'request_number', 'created_at', 'updated_at',
            'ready_at', 'converted_at', 'created_by', 'purchase_request'
        ]

    def get_created_by_full_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.username
        return ""

    def get_status_label(self, obj):
        return obj.get_status_display()


class PlanningRequestCreateSerializer(serializers.Serializer):
    """
    For creating a planning request from a department request.
    Planning can optionally provide initial item mappings.
    """
    department_request_id = serializers.IntegerField()
    # Bulk items payload during creation
    items = serializers.ListField(child=serializers.DictField(), required=False)
    attachments = AttachmentUploadSerializer(many=True, required=False)

    def validate_department_request_id(self, value):
        try:
            dr = DepartmentRequest.objects.get(id=value)
        except DepartmentRequest.DoesNotExist:
            raise serializers.ValidationError("Department request not found.")

        if dr.status != 'approved':
            raise serializers.ValidationError("Can only create planning requests from approved department requests.")

        return value

    def create(self, validated_data):
        from planning.services import create_planning_request_from_department

        dr_id = validated_data['department_request_id']
        dr = DepartmentRequest.objects.get(id=dr_id)
        user = self.context['request'].user
        attachments_data = validated_data.get('attachments', [])

        # Create planning request shell
        planning_request = create_planning_request_from_department(dr, user)

        # Auto-attach department request files to planning request
        ct_pr = ContentType.objects.get_for_model(PlanningRequest)
        for att in dr.files.all():
            FileAttachment.objects.create(
                asset=att.asset,
                uploaded_by=user,
                description=att.description,
                source_attachment=att,
                content_type=ct_pr,
                object_id=planning_request.id,
            )

        # Handle new attachments on creation
        if attachments_data:
            for att in attachments_data:
                source_attachment = None
                source_id = att.get('source_attachment_id')
                if source_id:
                    try:
                        source_attachment = FileAttachment.objects.get(id=source_id)
                    except FileAttachment.DoesNotExist:
                        raise serializers.ValidationError({"attachments": f"source_attachment_id {source_id} not found"})
                asset = FileAsset.objects.create(
                    file=att['file'],
                    uploaded_by=user,
                    description=att.get('description', '')
                )
                FileAttachment.objects.create(
                    asset=asset,
                    uploaded_by=user,
                    description=att.get('description', ''),
                    source_attachment=source_attachment,
                    content_type=ct_pr,
                    object_id=planning_request.id,
                )

        # If items provided, create them
        items_data = validated_data.get('items', [])
        max_order = planning_request.items.aggregate(max_order=django_models.Max('order')).get('max_order') or 0
        created_items = []
        for idx, item_data in enumerate(items_data):
            item_id = item_data.get('item_id')
            item_code = item_data.get('item_code')
            item = None
            if item_id:
                try:
                    item = Item.objects.get(id=item_id)
                except Item.DoesNotExist:
                    raise serializers.ValidationError({"items": f"Item at index {idx} with id {item_id} not found"})
            elif item_code:
                try:
                    item = Item.objects.get(code=item_code)
                except Item.DoesNotExist:
                    raise serializers.ValidationError({"items": f"Item at index {idx} with code {item_code} not found"})
            else:
                raise serializers.ValidationError({"items": f"Item at index {idx} requires item_id or item_code"})

            try:
                quantity = Decimal(str(item_data['quantity']))
            except Exception:
                raise serializers.ValidationError({"items": f"Item at index {idx} has invalid quantity"})

            created_items.append(
                PlanningRequestItem.objects.create(
                    planning_request=planning_request,
                    item=item,
                    job_no=item_data['job_no'],
                    quantity=quantity,
                    priority=item_data.get('priority', 'normal'),
                    specifications=item_data.get('specifications', ''),
                    source_item_index=item_data.get('source_item_index'),
                    order=max_order + idx + 1,
                )
            )

        return planning_request

    def validate_items(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Items must be a list.")
        for idx, item_data in enumerate(value):
            if 'job_no' not in item_data:
                raise serializers.ValidationError({"items": f"Item at index {idx} missing job_no"})
            if 'quantity' not in item_data:
                raise serializers.ValidationError({"items": f"Item at index {idx} missing quantity"})
            if 'item_id' not in item_data and 'item_code' not in item_data:
                raise serializers.ValidationError({"items": f"Item at index {idx} requires item_id or item_code"})
        return value


class BulkPlanningRequestItemSerializer(serializers.Serializer):
    """
    For bulk-creating multiple items at once.
    Each item can reference an existing catalog item by ID or code.
    """
    planning_request_id = serializers.IntegerField()
    items = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of items with: item_id/item_code, job_no, quantity, priority, specifications"
    )

    def validate_planning_request_id(self, value):
        try:
            pr = PlanningRequest.objects.get(id=value)
        except PlanningRequest.DoesNotExist:
            raise serializers.ValidationError("Planning request not found.")

        if pr.status != 'draft':
            raise serializers.ValidationError("Can only add items to draft planning requests.")

        return value

    def validate_items(self, value):
        """Validate each item in the list."""
        if not value:
            raise serializers.ValidationError("Items list cannot be empty.")

        for idx, item_data in enumerate(value):
            # Must have either item_id or item_code
            if 'item_id' not in item_data and 'item_code' not in item_data:
                raise serializers.ValidationError(
                    f"Item #{idx}: Must provide either 'item_id' or 'item_code'."
                )

            # Required fields
            if 'job_no' not in item_data:
                raise serializers.ValidationError(f"Item #{idx}: 'job_no' is required.")
            if 'quantity' not in item_data:
                raise serializers.ValidationError(f"Item #{idx}: 'quantity' is required.")

            # Validate quantity is positive
            try:
                qty = Decimal(str(item_data['quantity']))
                if qty <= 0:
                    raise serializers.ValidationError(f"Item #{idx}: Quantity must be positive.")
            except (ValueError, TypeError):
                raise serializers.ValidationError(f"Item #{idx}: Invalid quantity value.")

        return value

    def create(self, validated_data):
        """Bulk create planning request items."""
        pr_id = validated_data['planning_request_id']
        items_data = validated_data['items']

        planning_request = PlanningRequest.objects.get(id=pr_id)
        created_items = []

        # Get next order value
        max_order = PlanningRequestItem.objects.filter(
            planning_request=planning_request
        ).aggregate(max_order=django_models.Max('order'))['max_order'] or 0

        for idx, item_data in enumerate(items_data):
            # Resolve item
            item = None
            if 'item_id' in item_data:
                try:
                    item = Item.objects.get(id=item_data['item_id'])
                except Item.DoesNotExist:
                    raise serializers.ValidationError(f"Item #{idx}: Item ID {item_data['item_id']} not found.")
            elif 'item_code' in item_data:
                try:
                    item = Item.objects.get(code=item_data['item_code'])
                except Item.DoesNotExist:
                    raise serializers.ValidationError(
                        f"Item #{idx}: Item with code '{item_data['item_code']}' not found."
                    )

            # Create planning request item
            pri = PlanningRequestItem.objects.create(
                planning_request=planning_request,
                item=item,
                job_no=item_data['job_no'],
                quantity=Decimal(str(item_data['quantity'])),
                priority=item_data.get('priority', 'normal'),
                specifications=item_data.get('specifications', ''),
                source_item_index=item_data.get('source_item_index'),
                order=max_order + idx + 1,
            )
            created_items.append(pri)

        return {
            'planning_request': planning_request,
            'created_items': created_items,
            'count': len(created_items)
        }
