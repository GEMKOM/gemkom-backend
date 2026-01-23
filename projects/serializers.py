from rest_framework import serializers
from .models import (
    Customer, JobOrder, JobOrderFile,
    DepartmentTaskTemplate, DepartmentTaskTemplateItem,
    JobOrderDepartmentTask, DEPARTMENT_CHOICES
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

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'department', 'department_display', 'title',
            'status', 'status_display', 'sequence',
            'assigned_to', 'assigned_to_name',
            'can_start',
            'target_completion_date', 'completed_at'
        ]

    def get_can_start(self, obj):
        return obj.can_start()


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
    children = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()
    department_tasks = serializers.SerializerMethodField()
    department_tasks_count = serializers.SerializerMethodField()
    files = serializers.SerializerMethodField()
    files_count = serializers.SerializerMethodField()

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
            'parent', 'parent_title', 'children', 'children_count', 'hierarchy_level',
            'department_tasks', 'department_tasks_count',
            'files', 'files_count',
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
        return JobOrderChildSerializer(children, many=True).data

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()

    def get_department_tasks(self, obj):
        # Only return main tasks (no parent), ordered by sequence
        tasks = obj.department_tasks.filter(parent__isnull=True).order_by('sequence')
        return JobOrderDepartmentTaskNestedSerializer(tasks, many=True).data

    def get_department_tasks_count(self, obj):
        return obj.department_tasks.filter(parent__isnull=True).count()

    def get_files(self, obj):
        files = obj.files.all()
        return JobOrderFileNestedSerializer(files, many=True, context=self.context).data

    def get_files_count(self, obj):
        return obj.files.count()


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

class DepartmentTaskTemplateItemSerializer(serializers.ModelSerializer):
    """Serializer for template items."""
    department_display = serializers.CharField(source='get_department_display', read_only=True)
    title = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = DepartmentTaskTemplateItem
        fields = [
            'id', 'department', 'department_display', 'title',
            'sequence', 'depends_on'
        ]


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
    items = DepartmentTaskTemplateItemSerializer(many=True, read_only=True)
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
        read_only_fields = ['created_at', 'created_by', 'updated_at']


class DepartmentTaskTemplateCreateUpdateSerializer(serializers.ModelSerializer):
    """Serializer for creating/updating templates."""
    class Meta:
        model = DepartmentTaskTemplate
        fields = ['name', 'description', 'is_active', 'is_default']


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
            'status', 'status_display', 'assigned_to', 'assigned_to_name',
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

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title',
            'department', 'department_display', 'title',
            'status', 'status_display', 'sequence',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'parent', 'subtasks_count', 'can_start',
            'created_at'
        ]

    def get_subtasks_count(self, obj):
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()


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

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'id', 'job_order', 'job_order_title',
            'department', 'department_display', 'title', 'description',
            'status', 'status_display', 'sequence',
            'assigned_to', 'assigned_to_name',
            'target_start_date', 'target_completion_date',
            'started_at', 'completed_at',
            'depends_on', 'depends_on_tasks', 'can_start',
            'parent', 'parent_title', 'subtasks', 'subtasks_count',
            'notes',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'completed_by', 'completed_by_name'
        ]
        read_only_fields = [
            'started_at', 'completed_at',
            'created_at', 'created_by', 'updated_at', 'completed_by'
        ]

    def get_subtasks_count(self, obj):
        return obj.subtasks.count()

    def get_can_start(self, obj):
        return obj.can_start()


class DepartmentTaskCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating department tasks."""
    title = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'job_order', 'department', 'title', 'description',
            'assigned_to', 'target_start_date', 'target_completion_date',
            'depends_on', 'sequence',
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


class DepartmentTaskUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating department tasks."""
    class Meta:
        model = JobOrderDepartmentTask
        fields = [
            'title', 'description', 'assigned_to',
            'target_start_date', 'target_completion_date',
            'depends_on', 'sequence', 'notes'
        ]

    def validate(self, attrs):
        """Prevent updates on completed tasks."""
        instance = self.instance
        if instance and instance.status in ['completed', 'skipped']:
            raise serializers.ValidationError(
                "Tamamlanmış veya atlanan görevler güncellenemez."
            )
        return attrs


class ApplyTemplateSerializer(serializers.Serializer):
    """Serializer for applying a template to a job order."""
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=DepartmentTaskTemplate.objects.filter(is_active=True),
        required=True
    )

    def create_tasks_from_template(self, job_order, user):
        """Create department tasks from template."""
        template = self.validated_data['template_id']
        created_tasks = []
        task_mapping = {}  # template_item_id -> created_task

        # First pass: create all tasks (title auto-fills from job_order.title)
        for item in template.items.all().order_by('sequence'):
            task = JobOrderDepartmentTask.objects.create(
                job_order=job_order,
                department=item.department,
                sequence=item.sequence,
                created_by=user
            )
            created_tasks.append(task)
            task_mapping[item.id] = task

        # Second pass: set up dependencies
        for item in template.items.all():
            if item.depends_on.exists():
                task = task_mapping[item.id]
                for dep_item in item.depends_on.all():
                    if dep_item.id in task_mapping:
                        task.depends_on.add(task_mapping[dep_item.id])

        return created_tasks
