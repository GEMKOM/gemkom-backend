from rest_framework import serializers
from django.utils import timezone
from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES,
    JobOrderDiscussionTopic, JobOrderDiscussionComment,
    DiscussionAttachment, DiscussionNotification
)


class CustomerListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    class Meta:
        model = Customer
        fields = [
            'id', 'code', 'name', 'short_name', 'is_active',
            'default_currency', 'created_at'
        ]


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True,
        default=''
    )

    class Meta:
        model = Customer
        fields = [
            'id', 'code', 'name', 'short_name',
            'contact_person', 'phone', 'email', 'address',
            'tax_id', 'tax_office',
            'default_currency', 'is_active', 'notes',
            'created_at', 'created_by', 'created_by_name', 'updated_at'
        ]
        read_only_fields = ['created_at', 'created_by', 'updated_at']


class CustomerCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for create/update operations."""
    class Meta:
        model = Customer
        fields = [
            'code', 'name', 'short_name',
            'contact_person', 'phone', 'email', 'address',
            'tax_id', 'tax_office',
            'default_currency', 'is_active', 'notes'
        ]

    def validate_code(self, value):
        """Ensure code is uppercase and unique."""
        value = value.upper().strip()
        instance = self.instance
        if Customer.objects.filter(code=value).exclude(pk=instance.pk if instance else None).exists():
            raise serializers.ValidationError("Bu müşteri kodu zaten kullanımda.")
        return value


# ============================================================================
# JobOrder Serializers
# ============================================================================

class JobOrderChildSerializer(serializers.ModelSerializer):
    """Lightweight serializer for nested children in hierarchy."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'status', 'status_display',
            'completion_percentage', 'target_completion_date',
            'children_count'
        ]

    def get_children_count(self, obj):
        return obj.children.count()


class JobOrderListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()
    department_tasks_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'customer', 'customer_name', 'customer_code',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'completion_percentage',
            'parent', 'children_count', 'hierarchy_level',
            'department_tasks_count',
            'created_at'
        ]

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()

    def get_department_tasks_count(self, obj):
        return obj.department_tasks.filter(parent__isnull=True).count()


class JobOrderDepartmentTaskNestedSerializer(serializers.ModelSerializer):
    """Lightweight serializer for department tasks nested in job order detail."""
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        default=None
    )
    can_start = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'department', 'department_display', 'title',
            'status', 'status_display', 'sequence',
            'assigned_to', 'assigned_to_name',
            'can_start',
            'completion_percentage',
            'target_completion_date', 'completed_at'
        ]

    def get_can_start(self, obj):
        return obj.can_start()

    def get_completion_percentage(self, obj):
        return float(obj.get_completion_percentage())


class JobOrderDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True,
        default=''
    )
    completed_by_name = serializers.CharField(
        source='completed_by.get_full_name',
        read_only=True,
        default=''
    )
    parent_title = serializers.CharField(source='parent.title', read_only=True, default=None)
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()
    department_tasks_count = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()
    topics_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'description',
            'customer', 'customer_name', 'customer_code', 'customer_order_no',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'started_at', 'completed_at',
            'estimated_cost', 'labor_cost', 'material_cost',
            'subcontractor_cost', 'total_cost', 'cost_currency',
            'last_cost_calculation', 'completion_percentage',
            'parent', 'parent_title', 'children_count', 'hierarchy_level',
            'department_tasks_count', 'files_count', 'topics_count',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at', 'labor_cost', 'material_cost',
            'subcontractor_cost', 'total_cost', 'last_cost_calculation',
            'completion_percentage', 'created_at', 'created_by', 'updated_at',
            'completed_by'
        ]

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()

    def get_department_tasks_count(self, obj):
        return obj.department_tasks.filter(parent__isnull=True).count()

    def get_files_count(self, obj):
        return obj.files.count()

    def get_topics_count(self, obj):
        if obj.parent is not None:
            return 0
        return obj.discussion_topics.filter(is_deleted=False).count()


class JobOrderCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating job orders."""
    # Make customer optional - it's inherited from parent for child jobs
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'description',
            'customer', 'customer_order_no',
            'priority', 'target_completion_date',
            'estimated_cost', 'cost_currency',
            'parent'
        ]

    def validate_job_no(self, value):
        """Ensure job_no is uppercase and properly formatted."""
        value = value.upper().strip()
        if JobOrder.objects.filter(job_no=value).exists():
            raise serializers.ValidationError("Bu iş emri numarası zaten kullanımda.")
        return value

    def validate(self, attrs):
        """Validate parent-child relationship and customer inheritance."""
        parent = attrs.get('parent')
        job_no = attrs.get('job_no')
        customer = attrs.get('customer')

        if parent:
            # Child job_no should start with parent job_no
            if not job_no.startswith(parent.job_no):
                raise serializers.ValidationError({
                    'job_no': f"Alt iş numarası üst iş numarası ile başlamalıdır: {parent.job_no}"
                })
            # ALWAYS inherit customer from parent (ignore any provided value)
            attrs['customer'] = parent.customer
        else:
            # Root job - customer is required
            if not customer:
                raise serializers.ValidationError({
                    'customer': "Üst iş emri olmayan işler için müşteri zorunludur."
                })

        return attrs


class JobOrderUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating job orders."""
    class Meta:
        model = JobOrder
        fields = [
            'title', 'description', 'customer_order_no',
            'priority', 'target_completion_date',
            'estimated_cost', 'cost_currency'
        ]

    def validate(self, attrs):
        """Prevent certain updates on completed/cancelled jobs."""
        instance = self.instance
        if instance and instance.status in ['completed', 'cancelled']:
            raise serializers.ValidationError(
                "Tamamlanmış veya iptal edilmiş işler güncellenemez."
            )
        return attrs


# ============================================================================
# Job Order File Serializers
# ============================================================================

class JobOrderFileNestedSerializer(serializers.ModelSerializer):
    """Lightweight serializer for files nested in job order detail."""
    file_type_display = serializers.CharField(source='get_file_type_display', read_only=True)
    filename = serializers.CharField(read_only=True)
    file_size = serializers.IntegerField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderFile
        fields = [
            'id', 'file_url', 'filename', 'file_size',
            'file_type', 'file_type_display',
            'name', 'uploaded_at'
        ]

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class JobOrderFileSerializer(serializers.ModelSerializer):
    """Serializer for job order file attachments."""
    file_type_display = serializers.CharField(source='get_file_type_display', read_only=True)
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.get_full_name',
        read_only=True,
        default=''
    )
    filename = serializers.CharField(read_only=True)
    file_size = serializers.IntegerField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderFile
        fields = [
            'id', 'job_order', 'file', 'file_url', 'filename', 'file_size',
            'file_type', 'file_type_display',
            'name', 'description',
            'uploaded_at', 'uploaded_by', 'uploaded_by_name'
        ]
        read_only_fields = ['uploaded_at', 'uploaded_by']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class JobOrderFileUploadSerializer(serializers.ModelSerializer):
    """Serializer for uploading files to a job order."""
    class Meta:
        model = JobOrderFile
        fields = ['file', 'file_type', 'name', 'description']

    def validate_file(self, value):
        # Optional: Add file size/type validation
        max_size = 50 * 1024 * 1024  # 50MB
        if value.size > max_size:
            raise serializers.ValidationError("Dosya boyutu 50MB'dan büyük olamaz.")
        return value


# ============================================================================
# Department Task Template Serializers
# ============================================================================

class DepartmentTaskTemplateItemChildSerializer(serializers.ModelSerializer):
    """Serializer for child template items (subtasks)."""
    department_display = serializers.CharField(source='get_department_display', read_only=True)

    class Meta:
        model = DepartmentTaskTemplateItem
        fields = ['id', 'department', 'department_display', 'title', 'sequence', 'weight']


class DepartmentTaskTemplateItemSerializer(serializers.ModelSerializer):
    """Serializer for template items with children."""
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    title = serializers.CharField(required=False, allow_blank=True, default='')
    children = DepartmentTaskTemplateItemChildSerializer(many=True, read_only=True)
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentTaskTemplateItem
        fields = [
            'id', 'department', 'department_display', 'title',
            'sequence', 'weight', 'depends_on', 'parent',
            'children', 'children_count'
        ]

    def get_children_count(self, obj):
        return obj.children.count()


class DepartmentTaskTemplateListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for template list."""
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = DepartmentTaskTemplate
        fields = ['id', 'name', 'description', 'is_active', 'is_default', 'items_count', 'created_at']

    def get_items_count(self, obj):
        return obj.items.count()


class DepartmentTaskTemplateDetailSerializer(serializers.ModelSerializer):
    """Full serializer for template detail."""
    items = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True,
        default=''
    )

    class Meta:
        model = DepartmentTaskTemplate
        fields = [
            'id', 'name', 'description', 'is_active', 'is_default',
            'items', 'created_at', 'created_by', 'created_by_name', 'updated_at'
        ]

    def get_items(self, obj):
        # Only return main items (no parent), children are nested
        main_items = obj.items.filter(parent__isnull=True).order_by('sequence')
        return DepartmentTaskTemplateItemSerializer(main_items, many=True).data


class DepartmentTaskTemplateCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating templates."""
    class Meta:
        model = DepartmentTaskTemplate
        fields = ['name', 'description', 'is_active', 'is_default']


class DepartmentTaskTemplateItemUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating template items."""
    class Meta:
        model = DepartmentTaskTemplateItem
        fields = ['department', 'title', 'sequence', 'weight', 'depends_on']

    def validate_department(self, value):
        """Prevent department change if item has children."""
        instance = self.instance
        if instance and instance.children.exists():
            if value != instance.department:
                raise serializers.ValidationError(
                    "Alt öğeleri olan bir öğenin departmanı değiştirilemez."
                )
        return value


# ============================================================================
# Job Order Department Task Serializers
# ============================================================================

class DepartmentTaskSubtaskSerializer(serializers.ModelSerializer):
    """Lightweight serializer for subtasks."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        default=''
    )

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'title', 'department', 'department_display',
            'status', 'status_display', 'weight',
            'assigned_to', 'assigned_to_name',
            'target_completion_date', 'completed_at'
        ]


class DepartmentTaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list views."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        default=''
    )
    subtasks_count = serializers.SerializerMethodField()
    can_start = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title',
            'department', 'department_display', 'title',
            'status', 'status_display', 'sequence', 'weight',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'parent', 'subtasks_count', 'can_start',
            'completion_percentage',
            'created_at'
        ]

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items count for special tasks."""
        if obj.title == 'CNC Kesim':
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.title == 'Talaşlı İmalat':
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from planning.models import PlanningRequestItem
            return PlanningRequestItem.objects.filter(
                job_no=obj.job_order.job_no,
                quantity_to_purchase__gt=0
            ).count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_completion_percentage(self, obj):
        return float(obj.get_completion_percentage())


class DepartmentTaskDetailSerializer(serializers.ModelSerializer):
    """Full serializer for task detail views."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        default=''
    )
    created_by_name = serializers.CharField(
        source='created_by.get_full_name',
        read_only=True,
        default=''
    )
    completed_by_name = serializers.CharField(
        source='completed_by.get_full_name',
        read_only=True,
        default=''
    )
    parent_title = serializers.CharField(source='parent.title', read_only=True, default=None)
    subtasks = DepartmentTaskSubtaskSerializer(many=True, read_only=True)
    subtasks_count = serializers.SerializerMethodField()
    depends_on_tasks = DepartmentTaskSubtaskSerializer(source='depends_on', many=True, read_only=True)
    can_start = serializers.SerializerMethodField()
    procurement_progress = serializers.SerializerMethodField()
    cnc_progress = serializers.SerializerMethodField()
    machining_progress = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title',
            'department', 'department_display', 'title', 'description',
            'status', 'status_display', 'sequence', 'weight',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'depends_on', 'depends_on_tasks', 'can_start',
            'parent', 'parent_title', 'subtasks', 'subtasks_count',
            'procurement_progress', 'cnc_progress', 'machining_progress',
            'completion_percentage',
            'notes',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at',
            'created_at', 'created_by', 'updated_at', 'completed_by'
        ]

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items count for special tasks."""
        if obj.title == 'CNC Kesim':
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.title == 'Talaşlı İmalat':
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from planning.models import PlanningRequestItem
            return PlanningRequestItem.objects.filter(
                job_no=obj.job_order.job_no,
                quantity_to_purchase__gt=0
            ).count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_procurement_progress(self, obj):
        """Return procurement progress details for procurement tasks."""
        if obj.department != 'procurement':
            return None

        from decimal import Decimal
        from planning.models import PlanningRequestItem

        earned, total = obj.get_procurement_progress()

        items = PlanningRequestItem.objects.filter(
            job_no=obj.job_order.job_no,
            quantity_to_purchase__gt=0
        ).select_related('item')

        items_data = []
        for item in items:
            item_earned, item_total = item.get_procurement_progress()
            percentage = float((item_earned / item_total * 100).quantize(Decimal('0.01'))) if item_total > 0 else 0

            # Determine status based on percentage
            if percentage >= 100:
                status = 'paid'
            elif percentage >= 50:
                status = 'approved'
            elif percentage >= 40:
                status = 'submitted'
            else:
                status = 'pending'

            items_data.append({
                'id': item.id,
                'item_code': item.item.code if item.item else None,
                'item_name': item.item.name if item.item else item.item_description,
                'quantity': float(item.quantity_to_purchase),
                'unit_weight': float(item.item.unit_weight) if item.item else 1,
                'total_weight': float(item.total_weight),
                'progress': {
                    'percentage': percentage,
                    'status': status
                }
            })

        return {
            'percentage': float((earned / total * 100).quantize(Decimal('0.01'))) if total > 0 else 0,
            'total_weight': float(total),
            'earned_weight': float(earned),
            'items': items_data
        }

    def get_cnc_progress(self, obj):
        """Return CNC cutting progress details for CNC Kesim subtasks."""
        if obj.title != 'CNC Kesim':
            return None

        from decimal import Decimal
        from cnc_cutting.models import CncPart

        earned, total = obj.get_cnc_progress()

        cnc_parts = CncPart.objects.filter(
            job_no=obj.job_order.job_no
        ).select_related('cnc_task')

        parts_data = []
        for part in cnc_parts:
            part_weight = (part.weight_kg or Decimal('0')) * (part.quantity or 1)
            is_complete = part.cnc_task.completion_date is not None

            parts_data.append({
                'id': part.id,
                'job_no': part.job_no,
                'image_no': part.image_no,
                'position_no': part.position_no,
                'quantity': part.quantity,
                'weight_kg': float(part.weight_kg) if part.weight_kg else None,
                'total_weight': float(part_weight),
                'cnc_task_key': part.cnc_task.key,  # CncTask uses 'key' as primary key
                'cnc_task_complete': is_complete,
                'progress': {
                    'percentage': 100 if is_complete else 0,
                    'status': 'cut' if is_complete else 'pending'
                }
            })

        return {
            'percentage': float((earned / total * 100).quantize(Decimal('0.01'))) if total > 0 else 0,
            'total_weight': float(total),
            'earned_weight': float(earned),
            'parts': parts_data
        }

    def get_machining_progress(self, obj):
        """Return machining progress details for Talaşlı İmalat subtasks."""
        if obj.title != 'Talaşlı İmalat':
            return None

        from decimal import Decimal
        from tasks.models import Part, Operation
        from django.db.models import Sum, Q, ExpressionWrapper, FloatField, Value
        from django.db.models.functions import Coalesce

        earned, total = obj.get_machining_progress()

        parts = Part.objects.filter(
            job_no=obj.job_order.job_no
        ).prefetch_related('operations')

        parts_data = []
        for part in parts:
            # Get operations with annotated hours
            operations = Operation.objects.filter(part=part).annotate(
                total_hours_spent=Coalesce(
                    ExpressionWrapper(
                        Sum('timers__finish_time', filter=Q(timers__finish_time__isnull=False)) -
                        Sum('timers__start_time', filter=Q(timers__finish_time__isnull=False)),
                        output_field=FloatField()
                    ) / 3600000.0,
                    Value(0.0)
                )
            )

            # Calculate estimated and spent hours for this part
            estimated_hours = operations.aggregate(total=Sum('estimated_hours'))['total'] or Decimal('0.00')
            hours_spent = sum(Decimal(str(op.total_hours_spent)) for op in operations)

            # Calculate progress percentage
            if estimated_hours > 0:
                progress_pct = min(
                    float((hours_spent / estimated_hours * 100).quantize(Decimal('0.01'))),
                    100.0
                )
            else:
                progress_pct = 0.0

            parts_data.append({
                'id': part.key,
                'key': part.key,
                'name': part.name,
                'job_no': part.job_no,
                'image_no': part.image_no,
                'position_no': part.position_no,
                'quantity': part.quantity,
                'estimated_hours': float(estimated_hours),
                'hours_spent': float(hours_spent),
                'material': part.material,
                'dimensions': part.dimensions,
                'part_complete': part.completion_date is not None,
                'progress': {
                    'percentage': progress_pct,
                    'status': 'completed' if progress_pct >= 100 else 'in_progress'
                }
            })

        return {
            'percentage': float((earned / total * 100).quantize(Decimal('0.01'))) if total > 0 else 0,
            'total_hours': float(total),
            'earned_hours': float(earned),
            'parts': parts_data
        }

    def get_completion_percentage(self, obj):
        return float(obj.get_completion_percentage())


class DepartmentTaskCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating department tasks."""
    title = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'job_order', 'department', 'title', 'description',
            'assigned_to', 'target_start_date', 'target_completion_date',
            'depends_on', 'sequence', 'weight',
            'parent', 'notes'
        ]

    def validate(self, attrs):
        """Validate task creation."""
        parent = attrs.get('parent')
        job_order = attrs.get('job_order')

        # If subtask, ensure parent belongs to same job order
        if parent and parent.job_order != job_order:
            raise serializers.ValidationError({
                'parent': "Alt görev sadece aynı iş emrine ait bir göreve bağlanabilir."
            })

        # If subtask, inherit department from parent
        if parent:
            attrs['department'] = parent.department

        return attrs

    def create(self, validated_data):
        """Create task and set initial status based on dependencies."""
        # Extract depends_on from validated data (ManyToMany field)
        depends_on_tasks = validated_data.pop('depends_on', [])

        # Create the task
        task = super().create(validated_data)

        # Set dependencies if any
        if depends_on_tasks:
            task.depends_on.set(depends_on_tasks)

        # Update status based on dependencies
        task.update_status_from_dependencies()

        return task


class DepartmentTaskUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating department tasks."""
    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'title', 'description', 'assigned_to',
            'target_start_date', 'target_completion_date',
            'depends_on', 'sequence', 'weight', 'notes'
        ]

    def validate(self, attrs):
        """Prevent updates on completed tasks."""
        instance = self.instance
        if instance and instance.status in ['completed', 'skipped']:
            raise serializers.ValidationError(
                "Tamamlanmış veya atlanan görevler güncellenemez."
            )
        return attrs

    def update(self, instance, validated_data):
        """Update task and refresh status if dependencies changed."""
        depends_on_changed = 'depends_on' in validated_data

        # Update the task
        task = super().update(instance, validated_data)

        # If dependencies were changed, update status accordingly
        if depends_on_changed:
            task.update_status_from_dependencies()

        return task


class ApplyTemplateSerializer(serializers.Serializer):
    """Serializer for applying a template to a job order."""
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=DepartmentTaskTemplate.objects.filter(is_active=True),
        required=True
    )

    def create_tasks_from_template(self, job_order, user):
        """Create department tasks from template, including subtasks and weights."""
        template = self.validated_data['template_id']
        created_tasks = []
        task_mapping = {}  # template_item_id -> created_task

        # First pass: create main tasks (no parent)
        main_items = template.items.filter(parent__isnull=True).order_by('sequence')
        for item in main_items:
            task = JobOrderDepartmentTask.objects.create(
                job_order=job_order,
                department=item.department,
                title=item.title or '',  # Will auto-fill from job_order.title if empty
                sequence=item.sequence,
                weight=item.weight,  # Copy weight from template
                created_by=user
            )
            created_tasks.append(task)
            task_mapping[item.id] = task

            # Create children for this item
            for child_item in item.children.order_by('sequence'):
                child_task = JobOrderDepartmentTask.objects.create(
                    job_order=job_order,
                    department=child_item.department,
                    title=child_item.title,  # Subtasks keep their template title
                    sequence=child_item.sequence,
                    weight=child_item.weight,  # Copy weight from template
                    parent=task,
                    created_by=user
                )
                created_tasks.append(child_task)
                task_mapping[child_item.id] = child_task

        # Second pass: set up dependencies (only for main tasks)
        for item in main_items:
            if item.depends_on.exists():
                task = task_mapping[item.id]
                for dep_item in item.depends_on.all():
                    if dep_item.id in task_mapping:
                        task.depends_on.add(task_mapping[dep_item.id])

        return created_tasks


# ============================================================================
# Discussion System Serializers
# ============================================================================

class JobOrderDiscussionTopicListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    job_order_no = serializers.CharField(source='job_order.job_no', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    comment_count = serializers.SerializerMethodField()
    participant_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionTopic
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'title', 'priority', 'priority_display',
            'created_by', 'created_by_name', 'created_at',
            'is_edited', 'edited_at',
            'comment_count', 'participant_count'
        ]

    def get_comment_count(self, obj):
        return obj.get_comment_count()

    def get_participant_count(self, obj):
        return obj.get_participant_count()


class JobOrderDiscussionTopicDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    job_order_no = serializers.CharField(source='job_order.job_no', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default='')
    mentioned_users_data = serializers.SerializerMethodField()
    attachments_data = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionTopic
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'title', 'content', 'priority', 'priority_display',
            'created_by', 'created_by_name', 'created_by_username',
            'mentioned_users', 'mentioned_users_data',
            'attachments_data',
            'is_edited', 'edited_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'is_edited', 'edited_at']

    def get_mentioned_users_data(self, obj):
        return [{'id': u.id, 'username': u.username, 'full_name': u.get_full_name()} for u in obj.mentioned_users.all()]

    def get_attachments_data(self, obj):
        return [{'id': a.id, 'name': a.name, 'size': a.size, 'file_url': a.file.url if a.file else None, 'uploaded_by': a.uploaded_by.get_full_name() if a.uploaded_by else '', 'uploaded_at': a.uploaded_at} for a in obj.attachments.all()]


class JobOrderDiscussionTopicCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOrderDiscussionTopic
        fields = ['job_order', 'title', 'content', 'priority']

    def validate_job_order(self, value):
        if value.parent is not None:
            raise serializers.ValidationError("Tartışma konuları sadece ana iş emirleri için oluşturulabilir.")
        return value

    def create(self, validated_data):
        topic = super().create(validated_data)
        mentioned_users = topic.extract_mentions()
        if mentioned_users.exists():
            topic.mentioned_users.set(mentioned_users)
            # Send notifications after M2M is set
            from .signals import send_topic_notifications
            send_topic_notifications(topic)
        return topic


class JobOrderDiscussionTopicUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOrderDiscussionTopic
        fields = ['title', 'content', 'priority']

    def update(self, instance, validated_data):
        validated_data['is_edited'] = True
        validated_data['edited_at'] = timezone.now()
        topic = super().update(instance, validated_data)
        mentioned_users = topic.extract_mentions()
        topic.mentioned_users.set(mentioned_users)
        return topic


class JobOrderDiscussionCommentListSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default='')
    attachments_data = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionComment
        fields = [
            'id', 'topic', 'content',
            'created_by', 'created_by_name', 'created_by_username',
            'created_at', 'is_edited', 'edited_at',
            'attachments_data'
        ]

    def get_attachments_data(self, obj):
        return [{'id': a.id, 'name': a.name, 'size': a.size, 'file_url': a.file.url if a.file else None, 'uploaded_by': a.uploaded_by.get_full_name() if a.uploaded_by else '', 'uploaded_at': a.uploaded_at} for a in obj.attachments.all()]


class JobOrderDiscussionCommentDetailSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default='')
    mentioned_users_data = serializers.SerializerMethodField()
    attachments_data = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionComment
        fields = [
            'id', 'topic', 'content',
            'created_by', 'created_by_name', 'created_by_username',
            'mentioned_users', 'mentioned_users_data',
            'attachments_data',
            'is_edited', 'edited_at',
            'created_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'is_edited', 'edited_at']

    def get_mentioned_users_data(self, obj):
        return [{'id': u.id, 'username': u.username, 'full_name': u.get_full_name()} for u in obj.mentioned_users.all()]

    def get_attachments_data(self, obj):
        return [{'id': a.id, 'name': a.name, 'size': a.size, 'file_url': a.file.url if a.file else None, 'uploaded_by': a.uploaded_by.get_full_name() if a.uploaded_by else '', 'uploaded_at': a.uploaded_at} for a in obj.attachments.all()]


class JobOrderDiscussionCommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOrderDiscussionComment
        fields = ['topic', 'content']

    def validate_topic(self, value):
        if value.is_deleted:
            raise serializers.ValidationError("Bu konu silinmiş.")
        return value

    def create(self, validated_data):
        comment = super().create(validated_data)
        mentioned_users = comment.extract_mentions()
        if mentioned_users.exists():
            comment.mentioned_users.set(mentioned_users)
        # Send notifications after M2M is set
        from .signals import send_comment_notifications
        send_comment_notifications(comment)
        return comment


class JobOrderDiscussionCommentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOrderDiscussionComment
        fields = ['content']

    def update(self, instance, validated_data):
        validated_data['is_edited'] = True
        validated_data['edited_at'] = timezone.now()
        comment = super().update(instance, validated_data)
        mentioned_users = comment.extract_mentions()
        comment.mentioned_users.set(mentioned_users)
        return comment


class DiscussionAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.get_full_name', read_only=True, default='')

    class Meta:
        model = DiscussionAttachment
        fields = ['id', 'topic', 'comment', 'file', 'name', 'size', 'uploaded_by', 'uploaded_by_name', 'uploaded_at']
        read_only_fields = ['name', 'size', 'uploaded_by', 'uploaded_at']


class DiscussionNotificationSerializer(serializers.ModelSerializer):
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)
    topic_title = serializers.CharField(source='topic.title', read_only=True)
    topic_job_order = serializers.CharField(source='topic.job_order.job_no', read_only=True)
    comment_preview = serializers.SerializerMethodField()

    class Meta:
        model = DiscussionNotification
        fields = [
            'id', 'notification_type', 'notification_type_display',
            'topic', 'topic_title', 'topic_job_order',
            'comment', 'comment_preview',
            'is_read', 'created_at', 'read_at'
        ]
        read_only_fields = ['created_at', 'read_at']

    def get_comment_preview(self, obj):
        if obj.comment and obj.comment.content:
            return obj.comment.content[:100] + ('...' if len(obj.comment.content) > 100 else '')
        return None
