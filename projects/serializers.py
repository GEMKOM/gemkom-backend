from rest_framework import serializers
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth import get_user_model
from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, JobOrderDepartmentTaskFile, DEPARTMENT_CHOICES,
    JobOrderDiscussionTopic, JobOrderDiscussionComment,
    DiscussionAttachment,
    TechnicalDrawingRelease
)

# Groups that should receive drawing release notifications
DRAWING_RELEASE_STAKEHOLDER_GROUPS = [
    'procurement_team',
    'planning_team',
    'planning_manager',
    'manufacturing_team',
    'qualitycontrol_team',
    'logistics_team',
    'sales_team',
]


def get_drawing_release_stakeholders():
    """
    Get all active users from stakeholder groups who should receive
    drawing release notifications.
    """
    User = get_user_model()
    return User.objects.filter(
        is_active=True,
        groups__name__in=DRAWING_RELEASE_STAKEHOLDER_GROUPS,
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
    children_count = serializers.IntegerField(read_only=True)
    hierarchy_level = serializers.SerializerMethodField()
    ncr_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'quantity', 'customer', 'customer_name', 'customer_short_name', 'customer_code',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'completion_percentage',
            'parent', 'children_count', 'hierarchy_level',
            'ncr_count',
            'general_expenses_rate',
            'source_offer',
            'created_at'
        ]

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
    source_offer_no = serializers.CharField(source='source_offer.offer_no', read_only=True, default=None)
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
            'total_weight_kg', 'general_expenses_rate', 'completion_percentage',
            'parent', 'parent_title', 'children', 'children_count', 'hierarchy_level',
            'source_offer', 'source_offer_no',
            'files_count', 'topics_count',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at', 'completion_percentage',
            'created_at', 'created_by', 'updated_at', 'completed_by'
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
            'estimated_cost',
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
    job_no = serializers.CharField(required=False)
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        required=False,
    )

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'quantity', 'description', 'customer_order_no',
            'customer', 'priority', 'target_completion_date', 'incoterms',
            'estimated_cost', 'total_weight_kg', 'general_expenses_rate'
        ]

    def validate_job_no(self, value):
        value = value.upper().strip()
        if value != self.instance.job_no and JobOrder.objects.filter(job_no=value).exists():
            raise serializers.ValidationError("Bu iş emri numarası zaten kullanımda.")
        return value

    def validate(self, attrs):
        """Prevent certain updates on completed/cancelled jobs."""
        instance = self.instance
        if instance and instance.status in ['completed', 'cancelled']:
            raise serializers.ValidationError(
                "Tamamlanmış veya iptal edilmiş işler güncellenemez."
            )
        # For child jobs, customer is always inherited from parent — ignore any change.
        if instance and instance.parent_id and 'customer' in attrs:
            del attrs['customer']
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

    ALLOWED_EXTENSIONS = {
        '.pdf', '.dwg', '.dxf', '.step', '.stp', '.iges', '.igs',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp',
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv',
        '.zip', '.rar', '.7z',
    }

    def validate_file(self, value):
        import os
        max_size = 50 * 1024 * 1024  # 50MB
        if value.size > max_size:
            raise serializers.ValidationError("Dosya boyutu 50MB'dan büyük olamaz.")

        ext = os.path.splitext(value.name)[1].lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                f"Bu dosya türüne izin verilmiyor. İzin verilen türler: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )
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

class DepartmentTaskFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    filename = serializers.CharField(read_only=True)
    file_size = serializers.IntegerField(read_only=True)
    file_type_display = serializers.CharField(source='get_file_type_display', read_only=True)
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.get_full_name', read_only=True, default=''
    )

    class Meta:
        model = JobOrderDepartmentTaskFile
        fields = [
            'id', 'task', 'file', 'file_url', 'filename', 'file_size',
            'file_type', 'file_type_display', 'name', 'description',
            'uploaded_by', 'uploaded_by_name', 'uploaded_at',
        ]
        read_only_fields = ['task', 'uploaded_by', 'uploaded_at']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class DepartmentTaskFileUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobOrderDepartmentTaskFile
        fields = ['file', 'file_type', 'name', 'description']


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
    job_order_title = serializers.CharField(source='job_order.title', read_only=True, default=None)
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
    current_release_id = serializers.SerializerMethodField()
    pending_revision_request = serializers.SerializerMethodField()
    qc_required = serializers.BooleanField(read_only=True)
    has_qc_approval = serializers.BooleanField(read_only=True)
    qc_status = serializers.CharField(read_only=True)
    is_consultation = serializers.SerializerMethodField()
    offer_summary = serializers.SerializerMethodField()

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
            'is_under_revision', 'active_revision_release_id', 'current_release_id',
            'pending_revision_request',
            'qc_required', 'has_qc_approval', 'qc_status',
            'is_consultation', 'offer_summary',
            'created_at'
        ]

    def get_customer_name(self, obj):
        if obj.job_order_id:
            customer = obj.job_order.customer
            return customer.short_name or customer.name
        if obj.sales_offer_id:
            customer = obj.sales_offer.customer
            return customer.short_name or customer.name
        return None

    def get_is_consultation(self, obj):
        return bool(obj.sales_offer_id)

    def get_offer_summary(self, obj):
        if not obj.sales_offer_id:
            return None
        offer = obj.sales_offer
        return {
            'id': offer.id,
            'offer_no': offer.offer_no,
            'title': offer.title,
            'description': offer.description,
            'delivery_date_requested': offer.delivery_date_requested,
        }

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items/requests count for special tasks."""
        if not obj.job_order_id:
            return obj.subtasks.count()
        # Check both task_type and title for CNC tasks
        is_cnc_task = obj.task_type == 'cnc_cutting' or obj.title == 'CNC Kesim'
        if is_cnc_task:
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        # Check both task_type and title for machining tasks
        is_machining_task = obj.task_type == 'machining' or obj.title == 'Talaşlı İmalat'
        if is_machining_task:
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from planning.models import PlanningRequestItem
            return PlanningRequestItem.objects.filter(
                job_no=obj.job_order.job_no,
                quantity_to_purchase__gt=0,
            ).count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_completion_percentage(self, obj):
        return float(obj.get_completion_percentage())

    def _get_all_releases(self, obj):
        """Return all releases for top-level design tasks, cached per object."""
        if obj.department != 'design' or obj.parent is not None or not obj.job_order_id:
            return []
        if not hasattr(obj, '_cached_releases'):
            obj._cached_releases = list(obj.job_order.technical_drawing_releases.order_by('-revision_number'))
        return obj._cached_releases

    def get_is_under_revision(self, obj):
        return any(r.status == 'in_revision' for r in self._get_all_releases(obj))

    def get_active_revision_release_id(self, obj):
        for r in self._get_all_releases(obj):
            if r.status == 'in_revision':
                return r.id
        return None

    def get_current_release_id(self, obj):
        """Return the ID of the latest released (or in_revision) drawing release."""
        for r in self._get_all_releases(obj):
            if r.status in ('released', 'in_revision'):
                return r.id
        return None

    def get_pending_revision_request(self, obj):
        """Return pending revision request data for design tasks."""
        releases = self._get_all_releases(obj)
        if not releases:
            return None
        from .models import JobOrderDiscussionTopic
        release_ids = [r.id for r in releases]
        topic = JobOrderDiscussionTopic.objects.filter(
            related_release__in=release_ids,
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
    job_order_title = serializers.CharField(source='job_order.title', read_only=True, default=None)
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
    is_consultation = serializers.SerializerMethodField()
    offer_summary = serializers.SerializerMethodField()
    shared_files = serializers.SerializerMethodField()
    completion_files = serializers.SerializerMethodField()

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
            'is_consultation', 'offer_summary', 'shared_files',
            'notes', 'completion_files',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at',
            'created_at', 'created_by', 'updated_at', 'completed_by'
        ]

    def get_completion_files(self, obj):
        files = obj.completion_files.all()
        return DepartmentTaskFileSerializer(files, many=True, context=self.context).data

    def get_is_consultation(self, obj):
        return bool(obj.sales_offer_id)

    def get_offer_summary(self, obj):
        if not obj.sales_offer_id:
            return None
        offer = obj.sales_offer
        return {
            'id': offer.id,
            'offer_no': offer.offer_no,
            'title': offer.title,
            'description': offer.description,
            'delivery_date_requested': offer.delivery_date_requested,
        }

    def get_shared_files(self, obj):
        if not obj.sales_offer_id:
            return []
        request = self.context.get('request')
        result = []
        for f in obj.shared_files.all():
            file_url = request.build_absolute_uri(f.file.url) if f.file and request else None
            result.append({
                'id': f.id,
                'file_url': file_url,
                'filename': f.filename,
                'file_size': f.file_size,
                'file_type': f.file_type,
                'name': f.name,
                'uploaded_at': f.uploaded_at,
            })
        return result

    def get_subtasks_count(self, obj):
        """Return count of subtasks, or parts/items/requests count for special tasks."""
        if not obj.job_order_id:
            return obj.subtasks.count()
        # Check both task_type and title for CNC tasks
        is_cnc_task = obj.task_type == 'cnc_cutting' or obj.title == 'CNC Kesim'
        if is_cnc_task:
            from cnc_cutting.models import CncPart
            return CncPart.objects.filter(job_no=obj.job_order.job_no).count()
        # Check both task_type and title for machining tasks
        is_machining_task = obj.task_type == 'machining' or obj.title == 'Talaşlı İmalat'
        if is_machining_task:
            from tasks.models import Part
            return Part.objects.filter(job_no=obj.job_order.job_no).count()
        if obj.department == 'procurement':
            from planning.models import PlanningRequestItem
            return PlanningRequestItem.objects.filter(
                job_no=obj.job_order.job_no,
                quantity_to_purchase__gt=0,
            ).count()
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()

    def get_procurement_progress(self, obj):
        """Return procurement progress details for procurement tasks."""
        if obj.department != 'procurement' or not obj.job_order_id:
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
        if obj.title != 'CNC Kesim' or not obj.job_order_id:
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
        if obj.title != 'Talaşlı İmalat' or not obj.job_order_id:
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
        if obj.department != 'design' or obj.parent is not None or not obj.job_order_id:
            return TechnicalDrawingRelease.objects.none()
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
        """Prevent updates on completed/skipped tasks, except weight."""
        instance = self.instance
        if instance and instance.status in ['completed', 'skipped']:
            non_weight = {k for k in attrs if k != 'weight'}
            if non_weight:
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
        if (progress_changed or weight_changed) and task.job_order_id:
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

        all_mentioned_ids = set()
        if mentioned_users_from_content.exists():
            all_mentioned_ids.update(mentioned_users_from_content.values_list('id', flat=True))
        all_mentioned_ids.update(stakeholder_users.values_list('id', flat=True))

        if release.released_by_id:
            all_mentioned_ids.discard(release.released_by_id)

        if all_mentioned_ids:
            topic.mentioned_users.set(all_mentioned_ids)

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


class SubtaskItemSerializer(serializers.Serializer):
    """
    Recursive input serializer for a single node in a subtask tree.
    Department is NOT accepted — it is always inherited from the root parent task.
    depends_on is NOT accepted — M2M cannot be set during bulk_create.
    The subtasks field uses ListField(DictField) to defer recursive validation
    until the class is fully defined (validate_subtasks handles the recursion).
    """
    title = serializers.CharField(max_length=255)
    weight = serializers.IntegerField(default=10, min_value=1, max_value=100)
    sequence = serializers.IntegerField(default=1, min_value=1)
    task_type = serializers.ChoiceField(
        choices=[c[0] for c in JobOrderDepartmentTask.TASK_TYPE_CHOICES],
        required=False,
        allow_null=True,
        default=None,
    )
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.filter(is_active=True),
        required=False,
        allow_null=True,
        default=None,
    )
    target_start_date = serializers.DateField(required=False, allow_null=True, default=None)
    target_completion_date = serializers.DateField(required=False, allow_null=True, default=None)
    subtasks = serializers.ListField(child=serializers.DictField(), required=False, default=list)

    def validate_subtasks(self, value):
        validated = []
        for item in value:
            child = SubtaskItemSerializer(data=item)
            child.is_valid(raise_exception=True)
            validated.append(child.validated_data)
        return validated


class BulkCreateSubtasksSerializer(serializers.Serializer):
    """Top-level input wrapper for the bulk_create_subtasks endpoint."""
    tasks = SubtaskItemSerializer(many=True)

    def validate_tasks(self, value):
        if not value:
            raise serializers.ValidationError("En az bir görev gereklidir.")
        return value


# ============================================================================
# Cost Serializers
# ============================================================================

from .models import (
    JobOrderCostSummary, JobOrderProcurementLine,
    JobOrderQCCostLine, JobOrderShippingCostLine,
)
from procurement.models import Item as ProcurementItem
from planning.models import PlanningRequestItem


class JobOrderCostSummarySerializer(serializers.ModelSerializer):
    """Read/write serializer for JobOrderCostSummary. Cost fields are read-only."""
    general_expenses_rate = serializers.DecimalField(
        source='job_order.general_expenses_rate', max_digits=10, decimal_places=4, read_only=True
    )
    total_weight_kg = serializers.DecimalField(
        source='job_order.total_weight_kg', max_digits=12, decimal_places=2,
        read_only=True, allow_null=True
    )
    subcontractor_cost_at_100 = serializers.SerializerMethodField()
    paint_cost_at_100 = serializers.SerializerMethodField()
    paint_material_cost_at_100 = serializers.SerializerMethodField()

    class Meta:
        model = JobOrderCostSummary
        fields = [
            'job_order',
            'total_weight_kg',
            'labor_cost', 'material_cost', 'subcontractor_cost',
            'paint_cost', 'qc_cost', 'shipping_cost',
            'paint_material_rate', 'paint_material_cost',
            'general_expenses_rate', 'general_expenses_cost',
            'employee_overhead_rate', 'employee_overhead_cost',
            'actual_total_cost',
            'subcontractor_cost_at_100', 'paint_cost_at_100', 'paint_material_cost_at_100',
            'selling_price', 'selling_price_currency',
            'cost_not_applicable',
            'last_updated',
        ]
        read_only_fields = [
            'job_order',
            'total_weight_kg',
            'labor_cost', 'material_cost', 'subcontractor_cost',
            'paint_cost', 'qc_cost', 'shipping_cost',
            'paint_material_cost',
            'general_expenses_rate', 'general_expenses_cost',
            'employee_overhead_cost',
            'actual_total_cost',
            'last_updated',
        ]

    def get_subcontractor_cost_at_100(self, obj):
        from subcontracting.models import SubcontractingAssignment
        from projects.services.costing import convert_to_eur
        from datetime import date
        from decimal import Decimal
        today = date.today()
        assignments = (
            SubcontractingAssignment.objects
            .filter(
                department_task__job_order_id=obj.job_order_id,
                price_tier__isnull=False,
                allocated_weight_kg__gt=0,
            )
            .exclude(department_task__task_type='painting')
            .select_related('price_tier')
        )
        total = sum(
            convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, today)
            for a in assignments
        )
        return str(Decimal(total).quantize(Decimal('0.01')))

    def get_paint_cost_at_100(self, obj):
        from subcontracting.models import SubcontractingAssignment
        from projects.services.costing import convert_to_eur
        from datetime import date
        from decimal import Decimal
        today = date.today()
        assignments = (
            SubcontractingAssignment.objects
            .filter(
                department_task__job_order_id=obj.job_order_id,
                department_task__task_type='painting',
                price_tier__isnull=False,
                allocated_weight_kg__gt=0,
            )
            .select_related('price_tier')
        )
        total = sum(
            convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, today)
            for a in assignments
        )
        return str(Decimal(total).quantize(Decimal('0.01')))

    def get_paint_material_cost_at_100(self, obj):
        from projects.services.costing import convert_to_eur
        from datetime import date
        from decimal import Decimal
        weight = obj.job_order.total_weight_kg
        if not weight:
            return '0.00'
        today = date.today()
        total = convert_to_eur(obj.paint_material_rate * Decimal(str(weight)), 'TRY', today)
        return str(total)


class JobOrderProcurementLineSerializer(serializers.ModelSerializer):
    """Serializer for saved procurement cost lines."""
    item_code = serializers.CharField(source='item.code', read_only=True, default=None)
    item_name = serializers.CharField(source='item.name', read_only=True, default=None)
    item_unit = serializers.CharField(source='item.unit', read_only=True, default=None)

    class Meta:
        model = JobOrderProcurementLine
        fields = [
            'id', 'job_order',
            'item', 'item_code', 'item_name', 'item_unit',
            'item_description',
            'quantity', 'unit_price', 'amount_eur',
            'planning_request_item', 'order',
            'created_at',
        ]
        read_only_fields = ['id', 'amount_eur', 'created_at', 'item_code', 'item_name', 'item_unit']


class ProcurementLineInputSerializer(serializers.Serializer):
    """Single line input within a procurement submit request."""
    item = serializers.PrimaryKeyRelatedField(
        queryset=ProcurementItem.objects.all(),
        required=False, allow_null=True
    )
    item_description = serializers.CharField(max_length=500, default='', allow_blank=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, min_value=Decimal('0'))
    planning_request_item = serializers.PrimaryKeyRelatedField(
        queryset=PlanningRequestItem.objects.all(),
        required=False, allow_null=True
    )
    order = serializers.IntegerField(default=0, min_value=0)

    def validate(self, attrs):
        if not attrs.get('item') and not attrs.get('item_description'):
            raise serializers.ValidationError(
                "Either 'item' or 'item_description' must be provided."
            )
        return attrs


class ProcurementLinesSubmitSerializer(serializers.Serializer):
    """Replace all procurement lines for a job order atomically."""
    job_order = serializers.SlugRelatedField(
        slug_field='job_no',
        queryset=JobOrder.objects.all()
    )
    lines = ProcurementLineInputSerializer(many=True)

    def validate_lines(self, value):
        if value is None:
            return []
        return value


class ProcurementPreviewLineSerializer(serializers.Serializer):
    """Read-only preview line returned before submitting procurement cost lines."""
    planning_request_item = serializers.IntegerField()
    item = serializers.IntegerField(allow_null=True)
    item_code = serializers.CharField(allow_null=True)
    item_name = serializers.CharField(allow_null=True)
    item_unit = serializers.CharField(allow_null=True)
    item_description = serializers.CharField(allow_blank=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    unit_price_eur = serializers.DecimalField(max_digits=16, decimal_places=2, allow_null=True)
    original_unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, allow_null=True)
    original_currency = serializers.CharField(allow_null=True)
    price_source = serializers.ChoiceField(
        choices=['po_line', 'recommended_offer', 'any_offer', 'historical_po', 'none']
    )
    price_date = serializers.DateField(allow_null=True)
    order = serializers.IntegerField()


class JobOrderQCCostLineSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=None
    )

    class Meta:
        model = JobOrderQCCostLine
        fields = [
            'id', 'job_order',
            'description', 'amount', 'currency', 'amount_eur',
            'date', 'notes',
            'created_at', 'created_by', 'created_by_name', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'created_by', 'updated_at']

    def validate(self, attrs):
        if attrs.get('currency') == 'EUR':
            amount = attrs.get('amount')
            amount_eur = attrs.get('amount_eur')
            if amount is not None and amount_eur is not None and amount != amount_eur:
                raise serializers.ValidationError(
                    "When currency is EUR, amount_eur must equal amount."
                )
            # Auto-fill amount_eur from amount when currency is EUR
            if amount is not None and amount_eur is None:
                attrs['amount_eur'] = amount
        return attrs


class JobOrderShippingCostLineSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source='created_by.get_full_name', read_only=True, default=None
    )

    class Meta:
        model = JobOrderShippingCostLine
        fields = [
            'id', 'job_order',
            'description', 'amount', 'currency', 'amount_eur',
            'date', 'notes',
            'created_at', 'created_by', 'created_by_name', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'created_by', 'updated_at']

    def validate(self, attrs):
        if attrs.get('currency') == 'EUR':
            amount = attrs.get('amount')
            amount_eur = attrs.get('amount_eur')
            if amount is not None and amount_eur is not None and amount != amount_eur:
                raise serializers.ValidationError(
                    "When currency is EUR, amount_eur must equal amount."
                )
            if amount is not None and amount_eur is None:
                attrs['amount_eur'] = amount
        return attrs


class CostLineInputSerializer(serializers.Serializer):
    """Single line input for QC or shipping submit requests. Always EUR."""
    description = serializers.CharField(max_length=500)
    amount_eur = serializers.DecimalField(max_digits=16, decimal_places=2)
    date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=2000, default='', allow_blank=True)


class QCLinesSubmitSerializer(serializers.Serializer):
    """Replace all QC cost lines for a job order atomically."""
    job_order = serializers.SlugRelatedField(slug_field='job_no', queryset=JobOrder.objects.all())
    lines = CostLineInputSerializer(many=True)

    def validate_lines(self, value):
        return value if value is not None else []


class ShippingLinesSubmitSerializer(serializers.Serializer):
    """Replace all shipping cost lines for a job order atomically."""
    job_order = serializers.SlugRelatedField(slug_field='job_no', queryset=JobOrder.objects.all())
    lines = CostLineInputSerializer(many=True)

    def validate_lines(self, value):
        return value if value is not None else []


class CostTableRowSerializer(serializers.Serializer):
    """Read-only row in the cost table view."""
    job_no = serializers.CharField()
    title = serializers.CharField()
    customer_name = serializers.SerializerMethodField()
    status = serializers.CharField()

    # Costs from JobOrderCostSummary (may be null if no summary yet)
    labor_cost = serializers.SerializerMethodField()
    material_cost = serializers.SerializerMethodField()
    subcontractor_cost = serializers.SerializerMethodField()
    paint_cost = serializers.SerializerMethodField()
    qc_cost = serializers.SerializerMethodField()
    shipping_cost = serializers.SerializerMethodField()
    paint_material_cost = serializers.SerializerMethodField()
    general_expenses_cost = serializers.SerializerMethodField()
    employee_overhead_rate = serializers.SerializerMethodField()
    employee_overhead_cost = serializers.SerializerMethodField()
    actual_total_cost = serializers.SerializerMethodField()

    # From JobOrder
    estimated_cost = serializers.DecimalField(max_digits=16, decimal_places=2)
    general_expenses_rate = serializers.DecimalField(max_digits=10, decimal_places=4)
    total_weight_kg = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)

    # From JobOrderCostSummary
    selling_price = serializers.SerializerMethodField()
    selling_price_currency = serializers.SerializerMethodField()
    price_per_kg = serializers.SerializerMethodField()
    margin_eur = serializers.SerializerMethodField()
    margin_pct = serializers.SerializerMethodField()
    last_updated = serializers.SerializerMethodField()

    def _summary(self, obj):
        try:
            return obj.cost_summary
        except JobOrderCostSummary.DoesNotExist:
            return None

    def _at100(self, obj):
        """
        Compute at-100% projected costs for this job and all its descendants.

        Returns a dict with 'sc' (subcontractor), 'paint', 'pm' (paint_material).
        Results are cached per job_no on this serializer instance to avoid
        redundant queries when multiple fields are rendered.
        """
        if not hasattr(self, '_at100_cache'):
            self._at100_cache = {}
        if obj.job_no in self._at100_cache:
            return self._at100_cache[obj.job_no]

        from subcontracting.models import SubcontractingAssignment
        from projects.services.costing import convert_to_eur
        from projects.models import JobOrder as _JO
        from django.db.models import Q
        from decimal import Decimal

        prefix = f'{obj.job_no}-'

        # --- subcontractor at 100%: allocated_weight_kg × price_per_kg → EUR ---
        # Use each assignment's created_at date for FX (rate locked at contract time).
        sc_assignments = (
            SubcontractingAssignment.objects
            .filter(
                Q(department_task__job_order__job_no=obj.job_no) |
                Q(department_task__job_order__job_no__startswith=prefix),
                price_tier__isnull=False,
                allocated_weight_kg__gt=0,
            )
            .exclude(department_task__task_type='painting')
            .select_related('price_tier')
        )
        sc_total = sum(
            convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, a.created_at.date())
            for a in sc_assignments
        ) or Decimal('0')

        # --- paint at 100%: allocated_weight_kg × price_per_kg → EUR ---
        paint_assignments = (
            SubcontractingAssignment.objects
            .filter(
                Q(department_task__job_order__job_no=obj.job_no) |
                Q(department_task__job_order__job_no__startswith=prefix),
                department_task__task_type='painting',
                price_tier__isnull=False,
                allocated_weight_kg__gt=0,
            )
            .select_related('price_tier')
        )
        paint_total = sum(
            convert_to_eur(a.allocated_weight_kg * a.price_tier.price_per_kg, a.price_tier.currency, a.created_at.date())
            for a in paint_assignments
        ) or Decimal('0')

        # --- paint material at 100%: paint_material_rate × total_weight_kg → EUR ---
        # Sum across every job in the subtree using their own rate and weight.
        from datetime import date
        today = date.today()
        job_rows = list(
            _JO.objects
            .filter(Q(job_no=obj.job_no) | Q(job_no__startswith=prefix))
            .values('job_no', 'total_weight_kg')
        )
        job_nos = [r['job_no'] for r in job_rows]
        weight_map = {r['job_no']: r['total_weight_kg'] for r in job_rows}

        rate_map = dict(
            JobOrderCostSummary.objects
            .filter(job_order_id__in=job_nos)
            .values_list('job_order_id', 'paint_material_rate')
        )

        pm_total = Decimal('0')
        for jno in job_nos:
            weight = weight_map.get(jno)
            if not weight:
                continue
            rate = Decimal(str(rate_map.get(jno, '4.00')))
            pm_total += convert_to_eur(rate * Decimal(str(weight)), 'TRY', today)

        result = {
            'sc':    Decimal(sc_total).quantize(Decimal('0.01')),
            'paint': Decimal(paint_total).quantize(Decimal('0.01')),
            'pm':    pm_total.quantize(Decimal('0.01')),
        }
        self._at100_cache[obj.job_no] = result
        return result

    def get_customer_name(self, obj):
        if not obj.customer:
            return None
        return obj.customer.short_name or obj.customer.name

    def get_labor_cost(self, obj):
        s = self._summary(obj)
        return str(s.labor_cost) if s else '0.00'

    def get_material_cost(self, obj):
        s = self._summary(obj)
        return str(s.material_cost) if s else '0.00'

    def get_subcontractor_cost(self, obj):
        return str(self._at100(obj)['sc'])

    def get_paint_cost(self, obj):
        return str(self._at100(obj)['paint'])

    def get_qc_cost(self, obj):
        s = self._summary(obj)
        return str(s.qc_cost) if s else '0.00'

    def get_shipping_cost(self, obj):
        s = self._summary(obj)
        return str(s.shipping_cost) if s else '0.00'

    def get_paint_material_cost(self, obj):
        return str(self._at100(obj)['pm'])

    def get_general_expenses_cost(self, obj):
        s = self._summary(obj)
        return str(s.general_expenses_cost) if s else '0.00'

    def get_employee_overhead_rate(self, obj):
        s = self._summary(obj)
        return str(s.employee_overhead_rate) if s else '0.65'

    def get_employee_overhead_cost(self, obj):
        s = self._summary(obj)
        return str(s.employee_overhead_cost) if s else '0.00'

    def get_actual_total_cost(self, obj):
        from decimal import Decimal
        s = self._summary(obj)
        at100 = self._at100(obj)
        # Use stored actual values for non-progress-based components;
        # substitute at-100% projections for the three progress-based ones.
        labor      = s.labor_cost if s else Decimal('0')
        material   = s.material_cost if s else Decimal('0')
        qc         = s.qc_cost if s else Decimal('0')
        shipping   = s.shipping_cost if s else Decimal('0')
        gen_exp    = s.general_expenses_cost if s else Decimal('0')
        emp_oh     = s.employee_overhead_cost if s else Decimal('0')
        total = (labor + material + at100['sc'] + at100['paint']
                 + qc + shipping + at100['pm'] + gen_exp + emp_oh)
        return str(total.quantize(Decimal('0.01')))

    def _offer_price(self, obj):
        """Return the current SalesOfferPriceRevision for the job's source offer, or None."""
        offer = getattr(obj, 'source_offer', None)
        if offer is None:
            return None
        return offer.current_price

    def get_selling_price(self, obj):
        offer_price = self._offer_price(obj)
        if offer_price is not None:
            return str(offer_price.amount)
        s = self._summary(obj)
        return str(s.selling_price) if s else '0.00'

    def get_selling_price_currency(self, obj):
        offer_price = self._offer_price(obj)
        if offer_price is not None:
            return offer_price.currency
        s = self._summary(obj)
        return s.selling_price_currency if s else 'EUR'

    def get_price_per_kg(self, obj):
        """actual_total_cost ÷ total_weight_kg (null if weight is zero or missing)."""
        from decimal import Decimal
        weight = obj.total_weight_kg
        if not weight:
            return None
        total = Decimal(self.get_actual_total_cost(obj))
        if not total:
            return None
        return str((total / Decimal(str(weight))).quantize(Decimal('0.01')))

    def get_margin_eur(self, obj):
        from decimal import Decimal
        currency = self.get_selling_price_currency(obj)
        if currency != 'EUR':
            return None
        price = Decimal(self.get_selling_price(obj))
        if price == 0:
            return None
        total_at100 = Decimal(self.get_actual_total_cost(obj))
        return str(price - total_at100)

    def get_margin_pct(self, obj):
        from decimal import Decimal
        currency = self.get_selling_price_currency(obj)
        if currency != 'EUR':
            return None
        price = Decimal(self.get_selling_price(obj))
        if price == 0:
            return None
        total_at100 = Decimal(self.get_actual_total_cost(obj))
        pct = (price - total_at100) / price * 100
        return str(pct.quantize(Decimal('0.01')))

    def get_last_updated(self, obj):
        s = self._summary(obj)
        return s.last_updated.isoformat() if s else None
