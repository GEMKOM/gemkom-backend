from rest_framework import serializers
from .models import WeldingTimeEntry
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
