from rest_framework import serializers
from django.db import models as django_models
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from datetime import datetime
import json

from .models import DepartmentRequest, PlanningRequest, PlanningRequestItem, FileAsset, FileAttachment
from procurement.models import Item
from approvals.serializers import WorkflowSerializer
from approvals.models import ApprovalWorkflow


class SafeDateField(serializers.DateField):
    """
    DateField that tolerates datetime values by converting to date().
    """
    def to_representation(self, value):
        if isinstance(value, datetime):
            value = value.date()
        return super().to_representation(value)


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
    needed_date = SafeDateField()
    files = FileAttachmentSerializer(many=True, read_only=True)
    attachments = AttachmentUploadSerializer(many=True, write_only=True, required=False)
    request_number = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional. Provide ERP reference number. If not provided, will be auto-generated."
    )

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
            'created_at', 'submitted_at',
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

    def validate_request_number(self, value):
        """Validate request_number if provided manually."""
        if value and value.strip():
            # Check if request_number already exists
            if DepartmentRequest.objects.filter(request_number=value).exists():
                raise serializers.ValidationError(
                    f"Department request with number '{value}' already exists. Please use a unique number."
                )
            return value.strip()
        # Empty/blank values will trigger auto-generation
        return ''

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

        # Normalize items before creation (multipart often sends JSON string)
        items = validated_data.get('items', [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
                validated_data['items'] = items
            except Exception:
                raise serializers.ValidationError({"items": "Invalid items format; expected JSON list."})
        if not items:
            raise serializers.ValidationError({"items": "Cannot create request without items."})

        # Get uploaded files directly from request.FILES (same pattern as CncTaskDetailSerializer)
        uploaded_files = request.FILES.getlist('files') if request else []

        # Create the request object (initially as draft)
        dr = DepartmentRequest.objects.create(**validated_data)

        # Create file attachments for each uploaded file
        if uploaded_files:
            ct = ContentType.objects.get_for_model(dr)
            for file in uploaded_files:
                asset = FileAsset.objects.create(
                    file=file,
                    uploaded_by=request.user,
                    description=''
                )
                FileAttachment.objects.create(
                    asset=asset,
                    uploaded_by=request.user,
                    description='',
                    content_type=ct,
                    object_id=dr.id,
                )

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
    is_converted = serializers.ReadOnlyField()
    is_available = serializers.SerializerMethodField()
    purchase_request_info = serializers.SerializerMethodField()
    planning_request_number = serializers.CharField(source='planning_request.request_number', read_only=True)

    # For write operations
    item_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = PlanningRequestItem
        fields = [
            'id', 'item', 'item_id', 'item_code', 'item_name', 'item_unit',
            'job_no', 'quantity', 'priority', 'specifications',
            'source_item_index', 'order', 'files', 'attachments',
            'is_converted', 'is_available', 'purchase_request_info', 'planning_request', 'planning_request_number'
        ]
        read_only_fields = ['id']

    def get_is_available(self, obj):
        """
        Check if this planning request item is available for use in a new purchase request.
        An item is unavailable if it's already in an active purchase request (not rejected or cancelled).
        """
        from django.db.models import Q

        # Check if item is in any active purchase request
        active_prs = obj.purchase_requests.exclude(
            Q(status='rejected') | Q(status='cancelled')
        )

        return not active_prs.exists()

    def get_purchase_request_info(self, obj):
        """Get info about purchase requests this item was converted to"""
        purchase_requests = []
        for pr in obj.purchase_requests.all():
            purchase_requests.append({
                'id': pr.id,
                'request_number': pr.request_number,
                'title': pr.title,
                'status': pr.status
            })
        return purchase_requests if purchase_requests else None
    


class PlanningRequestSerializer(serializers.ModelSerializer):
    items = PlanningRequestItemSerializer(many=True, read_only=True)
    created_by_username = serializers.ReadOnlyField(source='created_by.username')
    created_by_full_name = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    department_request_number = serializers.CharField(source='department_request.request_number', read_only=True)
    completion_stats = serializers.SerializerMethodField()
    purchase_request_info = serializers.SerializerMethodField()
    files = FileAttachmentSerializer(many=True, read_only=True)
    department_files = FileAttachmentSerializer(many=True, read_only=True, source='department_request.files')

    class Meta:
        model = PlanningRequest
        fields = [
            'id', 'request_number', 'title', 'description', 'needed_date',
            'department_request', 'department_request_number',
            'created_by', 'created_by_username', 'created_by_full_name',
            'priority', 'status', 'status_label',
            'created_at', 'updated_at', 'ready_at', 'converted_at', 'completed_at',
            'completion_stats', 'purchase_request_info',
            'items', 'files', 'department_files'
        ]
        read_only_fields = [
            'request_number', 'created_at', 'updated_at',
            'ready_at', 'converted_at', 'completed_at', 'created_by'
        ]

    def get_created_by_full_name(self, obj):
        if obj.created_by:
            return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.username
        return ""

    def get_status_label(self, obj):
        return obj.get_status_display()

    def get_completion_stats(self, obj):
        """Get completion statistics for this planning request"""
        return obj.get_completion_stats()

    def get_purchase_request_info(self, obj):
        """Get info about all unique purchase requests created from this planning request's items"""
        purchase_requests = {}

        # Iterate through all items to find associated purchase requests
        for item in obj.items.all():
            for pr in item.purchase_requests.all():
                if pr.id not in purchase_requests:
                    purchase_requests[pr.id] = {
                        'id': pr.id,
                        'request_number': pr.request_number,
                        'title': pr.title,
                        'status': pr.status
                    }

        return list(purchase_requests.values())


class FlexibleAttachmentSerializer(serializers.Serializer):
    """
    Serializer for flexible file attachments that can be attached to multiple targets.
    attach_to can contain "request" and/or item indices (0, 1, 2, ...).

    Can attach either:
    1. New files via 'file' field
    2. Existing files via 'source_attachment_id' field (references existing FileAttachment)
    """
    file = serializers.FileField(required=False)
    source_attachment_id = serializers.IntegerField(required=False, help_text='ID of existing FileAttachment to reuse')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    attach_to = serializers.ListField(
        child=serializers.JSONField(),
        required=True,
        help_text='List of targets: "request" for the planning request, or item indices (0, 1, 2...)'
    )

    def validate(self, attrs):
        """Ensure either file or source_attachment_id is provided, but not both."""
        has_file = 'file' in attrs
        has_source = 'source_attachment_id' in attrs

        if not has_file and not has_source:
            raise serializers.ValidationError(
                "Either 'file' (new upload) or 'source_attachment_id' (existing file) must be provided."
            )

        if has_file and has_source:
            raise serializers.ValidationError(
                "Cannot provide both 'file' and 'source_attachment_id'. Choose one."
            )

        return attrs

    def validate_attach_to(self, value):
        if not value:
            raise serializers.ValidationError("attach_to cannot be empty.")
        for target in value:
            if target != "request" and not isinstance(target, int):
                raise serializers.ValidationError(f"Invalid target '{target}'. Must be 'request' or an integer item index.")
            if isinstance(target, int) and target < 0:
                raise serializers.ValidationError(f"Item index {target} cannot be negative.")
        return value


class PlanningRequestCreateSerializer(serializers.Serializer):
    """
    For creating a planning request, optionally from a department request.
    Planning can optionally provide initial item mappings.

    Files can be attached to multiple targets using the 'files' field:
    - "request": attach to the planning request
    - 0, 1, 2...: attach to items at those indices
    """
    department_request_id = serializers.IntegerField(required=False, allow_null=True)
    # Fields for standalone creation (required if no department_request_id)
    request_number = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        help_text="Optional. Provide ERP reference number. If not provided, will be auto-generated."
    )
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    needed_date = serializers.DateField(required=False, allow_null=True)
    priority = serializers.ChoiceField(choices=['low', 'normal', 'high', 'urgent'], default='normal', required=False)
    # Bulk items payload during creation
    items = serializers.ListField(child=serializers.DictField(), required=False)
    # Flexible file attachments
    files = FlexibleAttachmentSerializer(many=True, required=False)

    def to_internal_value(self, data):
        """
        Parse JSON strings for complex fields when sent via multipart/form-data.
        Handles both request.data (form fields) and request.FILES (file uploads).
        """
        import re
        from django.http import QueryDict

        # Get the request object to access FILES
        request = self.context.get('request')

        # Convert QueryDict to regular dict for easier manipulation
        if isinstance(data, QueryDict):
            parsed_data = {}
            for key in data.keys():
                parsed_data[key] = data.get(key)
        else:
            parsed_data = dict(data) if not isinstance(data, dict) else data.copy()

        # Parse 'items' if it's a JSON string
        if 'items' in parsed_data and isinstance(parsed_data['items'], str):
            try:
                parsed_data['items'] = json.loads(parsed_data['items'])
            except json.JSONDecodeError:
                raise serializers.ValidationError({"items": "Invalid JSON format for items field."})

        # Parse nested files structure from multipart format files[0].file, files[0].attach_to
        # into proper list of dicts
        files_dict = {}
        keys_to_remove = []

        # Process form data fields (attach_to, description, etc.)
        for key in list(parsed_data.keys()):
            if key.startswith('files['):
                keys_to_remove.append(key)
                match = re.match(r'files\[(\d+)\]\.(\w+)', key)
                if match:
                    index = int(match.group(1))
                    field_name = match.group(2)

                    if index not in files_dict:
                        files_dict[index] = {}

                    value = parsed_data[key]
                    # Parse attach_to if it's a JSON string
                    if field_name == 'attach_to' and isinstance(value, str):
                        try:
                            value = json.loads(value)
                        except json.JSONDecodeError:
                            raise serializers.ValidationError({
                                "files": f"Invalid JSON format for files[{index}].attach_to"
                            })

                    files_dict[index][field_name] = value

        # Process file uploads from request.FILES
        if request and hasattr(request, 'FILES'):
            for key in request.FILES.keys():
                if key.startswith('files['):
                    match = re.match(r'files\[(\d+)\]\.file', key)
                    if match:
                        index = int(match.group(1))
                        if index not in files_dict:
                            files_dict[index] = {}
                        files_dict[index]['file'] = request.FILES[key]

        # Remove the flattened keys from parsed_data
        for key in keys_to_remove:
            parsed_data.pop(key, None)

        # Convert files_dict to list if we found any files
        if files_dict:
            parsed_data['files'] = [files_dict[i] for i in sorted(files_dict.keys())]

        return super().to_internal_value(parsed_data)

    def validate_department_request_id(self, value):
        if value is None:
            return value
        try:
            dr = DepartmentRequest.objects.get(id=value)
        except DepartmentRequest.DoesNotExist:
            raise serializers.ValidationError("Department request not found.")

        if dr.status != 'approved':
            raise serializers.ValidationError("Can only create planning requests from approved department requests.")

        return value

    def validate_request_number(self, value):
        """Validate request_number if provided manually."""
        if value and value.strip():
            # Check if request_number already exists
            if PlanningRequest.objects.filter(request_number=value).exists():
                raise serializers.ValidationError(
                    f"Planning request with number '{value}' already exists. Please use a unique number."
                )
            return value.strip()
        # Empty/blank values will trigger auto-generation
        return ''

    def validate(self, attrs):
        # If no department_request_id, require title
        if not attrs.get('department_request_id'):
            if not attrs.get('title'):
                raise serializers.ValidationError({"title": "Title is required for standalone planning requests."})

        # Validate that file attachment targets reference valid item indices
        files_data = attrs.get('files', [])
        items_data = attrs.get('items', [])
        num_items = len(items_data)

        for file_idx, file_data in enumerate(files_data):
            for target in file_data.get('attach_to', []):
                if isinstance(target, int) and target >= num_items:
                    raise serializers.ValidationError({
                        "files": f"File at index {file_idx} references item index {target}, but only {num_items} items provided."
                    })

        return attrs

    def create(self, validated_data):
        from planning.services import create_planning_request_from_department, create_standalone_planning_request

        user = self.context['request'].user
        files_data = validated_data.get('files', [])
        dr_id = validated_data.get('department_request_id')
        manual_request_number = validated_data.get('request_number', '')
        ct_pr = ContentType.objects.get_for_model(PlanningRequest)
        ct_item = ContentType.objects.get_for_model(PlanningRequestItem)

        if dr_id:
            # Create from department request
            dr = DepartmentRequest.objects.get(id=dr_id)
            planning_request = create_planning_request_from_department(dr, user)

            # If manual request_number provided, update it
            if manual_request_number:
                planning_request.request_number = manual_request_number
                planning_request.save(update_fields=['request_number'])

            # Auto-attach department request files to planning request
            for att in dr.files.all():
                FileAttachment.objects.create(
                    asset=att.asset,
                    uploaded_by=user,
                    description=att.description,
                    source_attachment=att,
                    content_type=ct_pr,
                    object_id=planning_request.id,
                )
        else:
            # Create standalone planning request
            planning_request = create_standalone_planning_request(
                title=validated_data['title'],
                description=validated_data.get('description', ''),
                needed_date=validated_data.get('needed_date'),
                priority=validated_data.get('priority', 'normal'),
                created_by=user
            )

            # If manual request_number provided, update it
            if manual_request_number:
                planning_request.request_number = manual_request_number
                planning_request.save(update_fields=['request_number'])

        # Create items first (needed for file attachment targets)
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
                    # Create the item if it doesn't exist
                    item_name = item_data.get('item_name', item_code)
                    item_unit = item_data.get('item_unit', 'adet')
                    item = Item.objects.create(
                        code=item_code,
                        name=item_name,
                        unit=item_unit
                    )
            else:
                raise serializers.ValidationError({"items": f"Item at index {idx} requires item_id or item_code"})

            try:
                quantity = Decimal(str(item_data['quantity']))
            except Exception:
                raise serializers.ValidationError({"items": f"Item at index {idx} has invalid quantity"})

            planning_item = PlanningRequestItem.objects.create(
                planning_request=planning_request,
                item=item,
                job_no=item_data['job_no'],
                quantity=quantity,
                priority=item_data.get('priority', 'normal'),
                specifications=item_data.get('specifications', ''),
                source_item_index=item_data.get('source_item_index'),
                order=max_order + idx + 1,
            )
            created_items.append(planning_item)

        # Process flexible file attachments
        # Each file can be either a new upload or reference to an existing file
        for file_data in files_data:
            # Determine the asset to use
            if 'file' in file_data:
                # New file upload - create the asset
                asset = FileAsset.objects.create(
                    file=file_data['file'],
                    uploaded_by=user,
                    description=file_data.get('description', '')
                )
                source_attachment = None
            else:
                # Reference to existing attachment
                source_attachment_id = file_data['source_attachment_id']
                try:
                    source_attachment = FileAttachment.objects.select_related('asset').get(id=source_attachment_id)
                    asset = source_attachment.asset
                except FileAttachment.DoesNotExist:
                    raise serializers.ValidationError({
                        "files": f"FileAttachment with id {source_attachment_id} not found"
                    })

            # Attach to each target
            for target in file_data['attach_to']:
                if target == "request":
                    # Attach to the planning request
                    FileAttachment.objects.create(
                        asset=asset,
                        uploaded_by=user,
                        description=file_data.get('description', ''),
                        source_attachment=source_attachment if 'source_attachment_id' in file_data else None,
                        content_type=ct_pr,
                        object_id=planning_request.id,
                    )
                elif isinstance(target, int):
                    # Attach to the item at this index
                    FileAttachment.objects.create(
                        asset=asset,
                        uploaded_by=user,
                        description=file_data.get('description', ''),
                        source_attachment=source_attachment if 'source_attachment_id' in file_data else None,
                        content_type=ct_item,
                        object_id=created_items[target].id,
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
