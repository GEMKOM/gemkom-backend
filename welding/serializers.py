from rest_framework import serializers
from .models import WeldingTimeEntry, InternalTeamAssignment, WeldingPlanAllocation
from django.contrib.auth import get_user_model

User = get_user_model()


class WeldingTimeEntrySerializer(serializers.ModelSerializer):
    """
    Serializer for WeldingTimeEntry with support for both single and bulk operations.
    """
    employee_username = serializers.CharField(source='employee.username', read_only=True)
    employee_full_name = serializers.SerializerMethodField()
    overtime_type_display = serializers.CharField(source='get_overtime_type_display', read_only=True)
    overtime_multiplier = serializers.ReadOnlyField()
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    updated_by_username = serializers.CharField(source='updated_by.username', read_only=True, allow_null=True)

    class Meta:
        model = WeldingTimeEntry
        fields = [
            'id',
            'employee',
            'employee_username',
            'employee_full_name',
            'job_no',
            'date',
            'hours',
            'overtime_type',
            'overtime_type_display',
            'overtime_multiplier',
            'description',
            'created_at',
            'created_by',
            'created_by_username',
            'updated_at',
            'updated_by',
            'updated_by_username',
        ]
        read_only_fields = ['id', 'created_at', 'created_by', 'updated_at', 'updated_by']

    def get_employee_full_name(self, obj):
        """Get the full name of the employee."""
        return f"{obj.employee.first_name} {obj.employee.last_name}".strip() or obj.employee.username

    def validate_hours(self, value):
        """Ensure hours is positive and reasonable (max 24 hours per day)."""
        if value <= 0:
            raise serializers.ValidationError("Hours must be greater than 0")
        if value > 24:
            raise serializers.ValidationError("Hours cannot exceed 24 per day")
        return value

    def validate(self, attrs):
        """Custom validation logic."""
        # Only validate on create, not update
        if not self.instance:
            employee = attrs.get('employee')

            # Warn if trying to create entry for inactive employee
            if employee and not employee.is_active:
                raise serializers.ValidationError({
                    'employee': f"Cannot create time entry for inactive employee: {employee.username}. "
                                f"If this employee has returned to work, please reactivate their account first."
                })

        return attrs

    def create(self, validated_data):
        """Automatically set created_by from request context."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Automatically set updated_by from request context."""
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user
        return super().update(instance, validated_data)


class InternalTeamAssignmentInlineSerializer(serializers.ModelSerializer):
    """Compact serializer for embedding inside DepartmentTaskSubtaskSerializer."""
    team_name = serializers.CharField(source='team.name', read_only=True)
    team_foreman_name = serializers.SerializerMethodField()
    current_progress = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)

    class Meta:
        model = InternalTeamAssignment
        fields = ['id', 'team', 'team_name', 'team_foreman_name', 'allocated_weight_kg', 'notes', 'current_progress']

    def get_team_foreman_name(self, obj):
        if obj.team.foreman_id:
            return obj.team.foreman.get_full_name() or obj.team.foreman.username
        return None


class InternalTeamAssignmentSerializer(serializers.ModelSerializer):
    """Full serializer for list/detail/update responses."""
    team_name = serializers.CharField(source='team.name', read_only=True)
    team_foreman_name = serializers.SerializerMethodField()
    job_no = serializers.CharField(source='department_task.job_order_id', read_only=True)
    task_title = serializers.CharField(source='department_task.title', read_only=True)
    task_status = serializers.CharField(source='department_task.status', read_only=True)
    current_progress = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InternalTeamAssignment
        fields = [
            'id', 'department_task', 'job_no', 'task_title', 'task_status',
            'team', 'team_name', 'team_foreman_name',
            'allocated_weight_kg', 'notes',
            'current_progress',
            'created_at', 'created_by', 'created_by_name',
            'updated_at', 'updated_by', 'updated_by_name',
        ]
        read_only_fields = ['created_at', 'created_by', 'updated_at', 'updated_by']

    def get_team_foreman_name(self, obj):
        if obj.team.foreman_id:
            return obj.team.foreman.get_full_name() or obj.team.foreman.username
        return None

    def get_created_by_name(self, obj):
        if obj.created_by_id:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None

    def get_updated_by_name(self, obj):
        if obj.updated_by_id:
            return obj.updated_by.get_full_name() or obj.updated_by.username
        return None


class WeldingPlanAllocationSerializer(serializers.ModelSerializer):
    """Full serializer for the welding capacity planning board (list/detail/create/update)."""
    job_no = serializers.CharField(source='department_task.job_order_id', read_only=True)
    job_order_title = serializers.SerializerMethodField()
    subcontractor_name = serializers.CharField(source='subcontractor.name', read_only=True, allow_null=True)
    team_name = serializers.CharField(source='team.name', read_only=True, allow_null=True)
    resource_type = serializers.SerializerMethodField()
    resource_id = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    is_promoted = serializers.BooleanField(read_only=True)

    class Meta:
        model = WeldingPlanAllocation
        fields = [
            'id', 'department_task', 'job_no', 'job_order_title',
            'subcontractor', 'subcontractor_name',
            'team', 'team_name',
            'resource_type', 'resource_id',
            'allocated_weight_kg', 'planned_start_date', 'planned_end_date', 'notes',
            'progress', 'is_promoted',
            'created_at', 'created_by', 'updated_at', 'updated_by',
        ]
        read_only_fields = ['created_at', 'created_by', 'updated_at', 'updated_by']

    def get_job_order_title(self, obj):
        jo = obj.department_task.job_order if obj.department_task_id else None
        return jo.title if jo else None

    def get_resource_type(self, obj):
        if obj.subcontractor_id:
            return 'subcontractor'
        if obj.team_id:
            return 'team'
        return None

    def get_resource_id(self, obj):
        return obj.subcontractor_id or obj.team_id

    def get_progress(self, obj):
        return float(obj.current_progress)

    def validate(self, attrs):
        # Resolve effective values (instance ∪ attrs) so partial updates validate correctly.
        instance = self.instance

        if instance and instance.is_promoted:
            raise serializers.ValidationError(
                'Gerçek atamaya dönüştürülmüş tahsis düzenlenemez.'
            )

        department_task = attrs.get('department_task') or (instance.department_task if instance else None)
        subcontractor = attrs.get('subcontractor') if 'subcontractor' in attrs else (
            instance.subcontractor if instance else None
        )
        team = attrs.get('team') if 'team' in attrs else (instance.team if instance else None)

        # Parent must be a MAIN welding task (mirror welding/services/internal_team.py).
        if department_task is not None:
            is_welding = (
                department_task.task_type == 'welding'
                or department_task.title == 'Kaynaklı İmalat'
            )
            if not is_welding:
                raise serializers.ValidationError({
                    'department_task': "Yalnızca 'Kaynaklı İmalat' görevine tahsis yapılabilir."
                })
            if department_task.parent_id is not None:
                raise serializers.ValidationError({
                    'department_task': 'Tahsis yalnızca ana göreve yapılabilir, alt göreve değil.'
                })

        # Exactly one of subcontractor / team.
        if bool(subcontractor) == bool(team):
            raise serializers.ValidationError(
                'Taşeron veya ekipten yalnızca biri seçilmelidir.'
            )

        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['created_by'] = request.user
            validated_data['updated_by'] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['updated_by'] = request.user
        return super().update(instance, validated_data)


class WeldingPlanAllocationBulkItemSerializer(serializers.Serializer):
    """Shape validation for a single item in the bulk-save payload."""
    id = serializers.IntegerField(required=False)
    deleted = serializers.BooleanField(required=False, default=False)
    department_task = serializers.IntegerField(required=False)
    subcontractor = serializers.IntegerField(required=False, allow_null=True)
    team = serializers.IntegerField(required=False, allow_null=True)
    allocated_weight_kg = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    planned_start_date = serializers.DateField(required=False, allow_null=True)
    planned_end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class WeldingTimeEntryBulkCreateSerializer(serializers.Serializer):
    """
    Serializer for bulk creating welding time entries.
    Accepts a list of entries and creates them in a single transaction.
    """
    entries = WeldingTimeEntrySerializer(many=True)

    def create(self, validated_data):
        """Create multiple entries in a single transaction with batching for large datasets."""
        from welding.models import WeldingJobCostRecalcQueue

        entries_data = validated_data['entries']
        request = self.context.get('request')

        # Add created_by to each entry
        for entry_data in entries_data:
            if request and hasattr(request, 'user'):
                entry_data['created_by'] = request.user

        # Bulk create with batching for better memory management
        # For large datasets (>1000 rows), process in batches of 500
        BATCH_SIZE = 500
        all_entries = []

        entries_to_create = [WeldingTimeEntry(**entry_data) for entry_data in entries_data]

        for i in range(0, len(entries_to_create), BATCH_SIZE):
            batch = entries_to_create[i:i + BATCH_SIZE]
            created_batch = WeldingTimeEntry.objects.bulk_create(batch, batch_size=BATCH_SIZE)
            all_entries.extend(created_batch)

        # IMPORTANT: bulk_create() does NOT trigger Django signals!
        # Manually enqueue all affected jobs for cost recalculation
        unique_jobs = {entry.job_no for entry in all_entries if entry.job_no}
        for job_no in unique_jobs:
            WeldingJobCostRecalcQueue.objects.update_or_create(
                job_no=job_no,
                defaults={}
            )

        return {'entries': all_entries}

    def validate_entries(self, value):
        """Validate the list of entries."""
        if not value:
            raise serializers.ValidationError("At least one entry is required")

        return value
