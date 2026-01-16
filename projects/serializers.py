from rest_framework import serializers
from .models import Customer, JobOrder


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

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'status', 'status_display',
            'completion_percentage', 'target_completion_date'
        ]


class JobOrderListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_code = serializers.CharField(source='customer.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()

    class Meta:
        model = JobOrder
        fields = [
            'job_no', 'title', 'customer', 'customer_name', 'customer_code',
            'status', 'status_display', 'priority', 'priority_display',
            'target_completion_date', 'completion_percentage',
            'parent', 'children_count', 'hierarchy_level',
            'created_at'
        ]

    def get_children_count(self, obj):
        return obj.children.count()

    def get_hierarchy_level(self, obj):
        return obj.get_hierarchy_level()


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
    children = JobOrderChildSerializer(many=True, read_only=True)
    children_count = serializers.SerializerMethodField()
    hierarchy_level = serializers.SerializerMethodField()

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
