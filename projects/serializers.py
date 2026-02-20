from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES,
    JobOrderDiscussionTopic, JobOrderDiscussionComment,
    DiscussionAttachment, DiscussionNotification,
    TechnicalDrawingRelease
)

# Stakeholder teams that should receive drawing release notifications
DRAWING_RELEASE_STAKEHOLDER_TEAMS = [
    'procurement',      # Satın Alma
    'planning',         # Planlama
    'manufacturing',    # İmalat
    'qualitycontrol',   # Kalite Kontrol
    'logistics',        # Lojistik
    'sales',            # Proje Taahhüt
]


def get_drawing_release_stakeholders():
    """
    Get all active users from stakeholder teams who should receive
    drawing release notifications.
    """
    User = get_user_model()
    return User.objects.filter(
        is_active=True,
        profile__team__in=DRAWING_RELEASE_STAKEHOLDER_TEAMS
    ).distinct()


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
    customer_short_name = serializers.CharField(source='customer.short_name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'quantity', 'customer', 'customer_name', 'customer_short_name', 'customer_code',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'completion_percentage',
            'parent', 'children_count', 'hierarchy_level',
            'created_at'
        ]

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()


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
    customer_short_name = serializers.CharField(source='customer.short_name', read_only=True)
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
    children = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()
    topics_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'quantity', 'description',
            'customer', 'customer_name', 'customer_short_name', 'customer_code', 'customer_order_no',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'started_at', 'completed_at', 'incoterms',
            'estimated_cost', 'labor_cost', 'material_cost',
            'subcontractor_cost', 'total_cost', 'cost_currency',
            'total_weight_kg',
            'last_cost_calculation', 'completion_percentage',
            'parent', 'parent_title', 'children', 'children_count', 'hierarchy_level',
            'files_count', 'topics_count',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at', 'labor_cost', 'material_cost',
            'subcontractor_cost', 'total_cost', 'last_cost_calculation',
            'completion_percentage', 'created_at', 'created_by', 'updated_at',
            'completed_by'
        ]

    def get_children(self, obj):
        children = obj.children.order_by('job_no')
        return JobOrderListSerializer(children, many=True).data

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()

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
            'job_no', 'title', 'quantity', 'description',
            'customer', 'customer_order_no',
            'priority', 'target_completion_date', 'incoterms',
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
            'title', 'quantity', 'description', 'customer_order_no',
            'priority', 'target_completion_date', 'incoterms',
            'estimated_cost', 'cost_currency', 'total_weight_kg'
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
            'id', 'title', 'task_type', 'department', 'department_display',
            'status', 'status_display', 'weight',
            'assigned_to', 'assigned_to_name',
            'target_completion_date', 'completed_at'
        ]


class DepartmentTaskListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list views."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    customer_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.CharField(
        source='assigned_to.get_full_name',
        read_only=True,
        default=''
    )
    subtasks_count = serializers.SerializerMethodField()
    can_start = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()
    is_under_revision = serializers.SerializerMethodField()
    active_revision_release_id = serializers.SerializerMethodField()
    pending_revision_request = serializers.SerializerMethodField()
    qc_required = serializers.BooleanField(read_only=True)
    has_qc_approval = serializers.BooleanField(read_only=True)
    qc_status = serializers.CharField(read_only=True)

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title', 'customer_name',
            'department', 'department_display', 'title', 'task_type',
            'status', 'status_display', 'sequence', 'weight', 'manual_progress',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'parent', 'subtasks_count', 'can_start',
            'completion_percentage',
            'is_under_revision', 'active_revision_release_id',
            'pending_revision_request',
            'qc_required', 'has_qc_approval', 'qc_status',
            'created_at'
        ]

    def get_customer_name(self, obj):
        customer = obj.job_order.customer
        return customer.short_name or customer.name

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items/requests count for special tasks."""
        if obj.task_type == 'cnc_cutting':
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.task_type == 'machining':
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from procurement.models import PurchaseRequest
            return PurchaseRequest.objects.filter(
                planning_request_items__job_no=obj.job_order.job_no
            ).exclude(status='cancelled').distinct().count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_completion_percentage(self, obj):
        return float(obj.get_completion_percentage())

    def _get_design_releases(self, obj):
        """Return releases for top-level design tasks, or empty queryset."""
        if obj.department != 'design' or obj.parent is not None:
            return obj.job_order.technical_drawing_releases.none()
        return obj.job_order.technical_drawing_releases.all()

    def _get_revision_release(self, obj):
        return self._get_design_releases(obj).filter(status='in_revision').first()

    def get_is_under_revision(self, obj):
        return self._get_revision_release(obj) is not None

    def get_active_revision_release_id(self, obj):
        release = self._get_revision_release(obj)
        return release.id if release else None

    def get_pending_revision_request(self, obj):
        """Return pending revision request data for design tasks."""
        releases = self._get_design_releases(obj)
        if not releases.exists():
            return None
        # Find any release with a pending revision topic
        from .models import JobOrderDiscussionTopic
        topic = JobOrderDiscussionTopic.objects.filter(
            related_release__in=releases,
            topic_type='revision_request',
            revision_status='pending',
            is_deleted=False
        ).select_related('created_by', 'related_release').first()
        if not topic:
            return None
        return {
            'topic_id': topic.id,
            'release_id': topic.related_release_id,
            'revision_code': topic.related_release.revision_code if topic.related_release else None,
            'revision_number': topic.related_release.revision_number if topic.related_release else None,
            'reason': topic.content,
            'requested_by': topic.created_by.get_full_name() if topic.created_by else None,
            'requested_by_id': topic.created_by_id,
            'requested_at': topic.created_at,
        }


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
    is_under_revision = serializers.SerializerMethodField()
    active_revision_release_id = serializers.SerializerMethodField()
    pending_revision_request = serializers.SerializerMethodField()
    qc_required = serializers.BooleanField(read_only=True)
    has_qc_approval = serializers.BooleanField(read_only=True)
    qc_status = serializers.CharField(read_only=True)

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title',
            'department', 'department_display', 'title', 'task_type', 'description',
            'status', 'status_display', 'sequence', 'weight', 'manual_progress',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'depends_on', 'depends_on_tasks', 'can_start',
            'parent', 'parent_title', 'subtasks', 'subtasks_count',
            'procurement_progress', 'cnc_progress', 'machining_progress',
            'completion_percentage',
            'is_under_revision', 'active_revision_release_id',
            'pending_revision_request',
            'qc_required', 'has_qc_approval', 'qc_status',
            'notes',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at',
            'created_at', 'created_by', 'updated_at', 'completed_by'
        ]

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items/requests count for special tasks."""
        if obj.task_type == 'cnc_cutting':
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.task_type == 'machining':
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from procurement.models import PurchaseRequest
            return PurchaseRequest.objects.filter(
                planning_request_items__job_no=obj.job_order.job_no
            ).exclude(status='cancelled').distinct().count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_procurement_progress(self, obj):
        """Return procurement progress details for procurement tasks."""
        if obj.department != 'procurement':
            return None

        from decimal import Decimal
        from procurement.models import PurchaseRequest

        earned, total = obj.get_procurement_progress()

        # Get purchase requests that have items allocated to this job order
        purchase_requests = PurchaseRequest.objects.filter(
            planning_request_items__job_no=obj.job_order.job_no
        ).exclude(
            status='cancelled'
        ).distinct().select_related('requestor').prefetch_related(
            'request_items__item',
            'planning_request_items'
        ).order_by('-created_at')

        requests_data = []
        for pr in purchase_requests:
            # Count items for this job order
            job_items = pr.planning_request_items.filter(job_no=obj.job_order.job_no)
            items_count = job_items.count()

            # Get item names for this job
            item_names = [
                item.item.name if item.item else item.item_description
                for item in job_items[:3]
            ]
            if job_items.count() > 3:
                item_names.append(f'+{job_items.count() - 3} more')

            requests_data.append({
                'id': pr.id,
                'request_number': pr.request_number,
                'title': pr.title,
                'status': pr.status,
                'status_display': pr.get_status_display(),
                'priority': pr.priority,
                'requestor': pr.requestor.get_full_name() if pr.requestor else None,
                'items_count': items_count,
                'item_names': item_names,
                'created_at': pr.created_at,
                'submitted_at': pr.submitted_at,
            })

        return {
            'percentage': float((earned / total * 100).quantize(Decimal('0.01'))) if total > 0 else 0,
            'total_weight': float(total),
            'earned_weight': float(earned),
            'requests': requests_data
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

    def _get_design_releases(self, obj):
        """Return releases for top-level design tasks, or empty queryset."""
        if obj.department != 'design' or obj.parent is not None:
            return obj.job_order.technical_drawing_releases.none()
        return obj.job_order.technical_drawing_releases.all()

    def _get_revision_release(self, obj):
        return self._get_design_releases(obj).filter(status='in_revision').first()

    def get_is_under_revision(self, obj):
        return self._get_revision_release(obj) is not None

    def get_active_revision_release_id(self, obj):
        release = self._get_revision_release(obj)
        return release.id if release else None

    def get_pending_revision_request(self, obj):
        """Return pending revision request data for design tasks."""
        releases = self._get_design_releases(obj)
        if not releases.exists():
            return None
        from .models import JobOrderDiscussionTopic
        topic = JobOrderDiscussionTopic.objects.filter(
            related_release__in=releases,
            topic_type='revision_request',
            revision_status='pending',
            is_deleted=False
        ).select_related('created_by', 'related_release').first()
        if not topic:
            return None
        return {
            'topic_id': topic.id,
            'release_id': topic.related_release_id,
            'revision_code': topic.related_release.revision_code if topic.related_release else None,
            'revision_number': topic.related_release.revision_number if topic.related_release else None,
            'reason': topic.content,
            'requested_by': topic.created_by.get_full_name() if topic.created_by else None,
            'requested_by_id': topic.created_by_id,
            'requested_at': topic.created_at,
        }


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
            'depends_on', 'sequence', 'weight', 'manual_progress', 'notes'
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
        progress_changed = 'manual_progress' in validated_data
        weight_changed = 'weight' in validated_data

        # Update the task
        task = super().update(instance, validated_data)

        # If dependencies were changed, update status accordingly
        if depends_on_changed:
            task.update_status_from_dependencies()

        # If manual progress or weight changed, update job order completion
        if progress_changed or weight_changed:
            task.job_order.update_completion_percentage()

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
                task_type=item.task_type or None,
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
                    task_type=child_item.task_type or None,
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
    topic_type_display = serializers.CharField(source='get_topic_type_display', read_only=True)
    revision_status_display = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    revision_assigned_to_name = serializers.CharField(
        source='revision_assigned_to.get_full_name', read_only=True, default=None
    )
    comment_count = serializers.SerializerMethodField()
    participant_count = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionTopic
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'title', 'priority', 'priority_display',
            'topic_type', 'topic_type_display',
            'revision_status', 'revision_status_display',
            'revision_assigned_to', 'revision_assigned_to_name',
            'related_release',
            'created_by', 'created_by_name', 'created_at',
            'is_edited', 'edited_at',
            'comment_count', 'participant_count'
        ]

    def get_comment_count(self, obj):
        return obj.get_comment_count()

    def get_participant_count(self, obj):
        return obj.get_participant_count()

    def get_revision_status_display(self, obj):
        return obj.get_revision_status_display() if obj.revision_status else None


class JobOrderDiscussionTopicDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    job_order_no = serializers.CharField(source='job_order.job_no', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    topic_type_display = serializers.CharField(source='get_topic_type_display', read_only=True)
    revision_status_display = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True, default='')
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default='')
    revision_assigned_to_name = serializers.CharField(
        source='revision_assigned_to.get_full_name', read_only=True, default=None
    )
    related_release_data = serializers.SerializerMethodField()
    mentioned_users_data = serializers.SerializerMethodField()
    attachments_data = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderDiscussionTopic
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'title', 'content', 'priority', 'priority_display',
            'topic_type', 'topic_type_display',
            'revision_status', 'revision_status_display',
            'revision_assigned_to', 'revision_assigned_to_name',
            'related_release', 'related_release_data',
            'created_by', 'created_by_name', 'created_by_username',
            'mentioned_users', 'mentioned_users_data',
            'attachments_data',
            'is_edited', 'edited_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'is_edited', 'edited_at']

    def get_revision_status_display(self, obj):
        return obj.get_revision_status_display() if obj.revision_status else None

    def get_related_release_data(self, obj):
        if not obj.related_release:
            return None
        return {
            'id': obj.related_release.id,
            'revision_number': obj.related_release.revision_number,
            'revision_code': obj.related_release.revision_code,
            'status': obj.related_release.status
        }

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


# ============================================================================
# Technical Drawing Release Serializers
# ============================================================================

class TechnicalDrawingReleaseListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    job_order_no = serializers.CharField(source='job_order.job_no', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    released_by_name = serializers.CharField(source='released_by.get_full_name', read_only=True, default='')

    class Meta:
        model = TechnicalDrawingRelease
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'revision_number', 'revision_code', 'folder_path',
            'status', 'status_display',
            'released_by', 'released_by_name', 'released_at',
            'hardcopy_count', 'changelog'
        ]


class TechnicalDrawingReleaseDetailSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    job_order_no = serializers.CharField(source='job_order.job_no', read_only=True)
    job_order_title = serializers.CharField(source='job_order.title', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    released_by_name = serializers.CharField(source='released_by.get_full_name', read_only=True, default='')
    release_topic_id = serializers.IntegerField(source='release_topic.id', read_only=True, default=None)
    pending_revision_requests = serializers.SerializerMethodField()

    class Meta:
        model = TechnicalDrawingRelease
        fields = [
            'id', 'job_order', 'job_order_no', 'job_order_title',
            'revision_number', 'revision_code', 'folder_path',
            'changelog', 'hardcopy_count',
            'status', 'status_display',
            'released_by', 'released_by_name', 'released_at',
            'release_topic_id', 'pending_revision_requests',
            'created_at', 'updated_at'
        ]

    def get_pending_revision_requests(self, obj):
        """Get pending revision request topics for this release."""
        pending_topics = obj.revision_topics.filter(
            revision_status='pending',
            is_deleted=False
        )
        return [{
            'id': t.id,
            'title': t.title,
            'created_by': t.created_by.get_full_name() if t.created_by else '',
            'created_at': t.created_at
        } for t in pending_topics]


class TechnicalDrawingReleaseCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new release."""
    topic_content = serializers.CharField(write_only=True, required=False, allow_blank=True)
    auto_complete_design_task = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = TechnicalDrawingRelease
        fields = [
            'job_order', 'folder_path', 'changelog',
            'revision_code', 'hardcopy_count', 'topic_content',
            'auto_complete_design_task'
        ]

    def create(self, validated_data):
        topic_content = validated_data.pop('topic_content', '')
        auto_complete_design_task = validated_data.pop('auto_complete_design_task', False)
        job_order = validated_data['job_order']

        # Set revision number
        validated_data['revision_number'] = TechnicalDrawingRelease.get_next_revision_number(job_order)

        release = super().create(validated_data)

        # Create release topic
        topic_title = f"Teknik Çizim Yayını - Rev.{release.revision_code or release.revision_number}"

        # Build topic content in the same format as the notification email
        if topic_content:
            content = topic_content
        else:
            released_by_name = release.released_by.get_full_name() if release.released_by else 'Bilinmeyen'
            content = f"""{released_by_name} yeni teknik çizim yayınladı:

İş Emri: {job_order.job_no} - {job_order.title}
Revizyon: {release.revision_code or release.revision_number}
Hardcopy: {release.hardcopy_count} set planlama birimine bırakılacaktır.

Klasör Yolu:
{release.folder_path}

Değişiklikler:
{release.changelog}"""

        topic = JobOrderDiscussionTopic.objects.create(
            job_order=job_order,
            title=topic_title,
            content=content,
            priority='normal',
            topic_type='drawing_release',
            created_by=release.released_by
        )

        # Extract mentions from content and add stakeholder teams
        mentioned_users_from_content = topic.extract_mentions()
        stakeholder_users = get_drawing_release_stakeholders()

        # Combine mentioned users and stakeholders (excluding the releaser)
        all_mentioned_ids = set()
        if mentioned_users_from_content.exists():
            all_mentioned_ids.update(mentioned_users_from_content.values_list('id', flat=True))
        all_mentioned_ids.update(stakeholder_users.values_list('id', flat=True))

        # Exclude the person who released
        if release.released_by_id:
            all_mentioned_ids.discard(release.released_by_id)

        if all_mentioned_ids:
            topic.mentioned_users.set(all_mentioned_ids)

        # Link topic to release
        release.release_topic = topic
        release.save(update_fields=['release_topic'])

        # Auto-complete design department task if flag is set
        if auto_complete_design_task:
            design_task = job_order.department_tasks.filter(
                department='design',
                parent__isnull=True
            ).first()
            if design_task and design_task.status == 'in_progress':
                design_task.complete(user=release.released_by)

        # Send notifications
        from .signals import send_drawing_released_notifications
        send_drawing_released_notifications(release, topic)

        return release


class RevisionRequestSerializer(serializers.Serializer):
    """Serializer for requesting a revision."""
    reason = serializers.CharField(required=True)


class ApproveRevisionSerializer(serializers.Serializer):
    """Serializer for approving a revision request."""
    topic_id = serializers.IntegerField(required=True)
    assigned_to = serializers.IntegerField(required=False, allow_null=True)


class SelfRevisionSerializer(serializers.Serializer):
    """Serializer for self-initiating a revision."""
    reason = serializers.CharField(required=True)


class CompleteRevisionSerializer(serializers.Serializer):
    """Serializer for completing a revision."""
    folder_path = serializers.CharField(required=True)
    changelog = serializers.CharField(required=False, allow_blank=True)
    revision_code = serializers.CharField(required=False, allow_blank=True)
    hardcopy_count = serializers.IntegerField(required=False, default=0)
    topic_content = serializers.CharField(required=False, allow_blank=True)


class RejectRevisionSerializer(serializers.Serializer):
    """Serializer for rejecting a revision request."""
    topic_id = serializers.IntegerField(required=True)
    reason = serializers.CharField(required=True)
