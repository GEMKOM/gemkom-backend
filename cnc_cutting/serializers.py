import json
from core.serializers import NullablePKRelatedField
from rest_framework import serializers

from machines.models import Machine
from .models import CncTask, CncPart, RemnantPlate
from tasks.models import TaskKeyCounter, TaskFile
from tasks.serializers import BaseTimerSerializer, TaskFileSerializer
from django.db import transaction
from django.db.utils import IntegrityError

class CncPartSerializer(serializers.ModelSerializer):
    """
    Serializer for the CncPart model. Used for nested representation
    within a CncTask.
    """
    class Meta:
        model = CncPart
        fields = ['id', 'cnc_task', 'job_no', 'image_no', 'position_no', 'weight_kg', 'quantity']


class CncPartSearchResultSerializer(serializers.ModelSerializer):
    """
    Serializer for CNC part search results.
    Returns part information along with its parent CNC task details.
    """
    nesting_id = serializers.CharField(source='cnc_task.nesting_id', read_only=True)
    planned_start_ms = serializers.IntegerField(source='cnc_task.planned_start_ms', read_only=True)
    planned_end_ms = serializers.IntegerField(source='cnc_task.planned_end_ms', read_only=True)
    completion_date = serializers.IntegerField(source='cnc_task.completion_date', read_only=True)

    class Meta:
        model = CncPart
        fields = [
            'id', 'job_no', 'image_no', 'position_no', 'weight_kg', 'quantity',
            'nesting_id', 'planned_start_ms', 'planned_end_ms', 'completion_date'
        ]


class CncTimerSerializer(BaseTimerSerializer):
    """
    Extends the BaseTimerSerializer to include fields specific to a CncTask.
    """
    nesting_id = serializers.CharField(source='issue_key.nesting_id', read_only=True)
    thickness_mm = serializers.CharField(source='issue_key.thickness_mm', read_only=True)

    class Meta(BaseTimerSerializer.Meta):
        # Inherit fields from the base and add the new ones
        fields = BaseTimerSerializer.Meta.fields + [
            'nesting_id', 'thickness_mm'
        ]


class CncTaskListSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for listing CncTask instances.
    It excludes the nested 'parts' for performance.
    """
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True)
    total_hours_spent = serializers.SerializerMethodField()
    parts_count = serializers.IntegerField(read_only=True)

    def get_total_hours_spent(self, obj):
        # Use the reverse generic relation. Django automatically provides this.
        # The related_name on the GFK is 'issue_key'.
        timers = obj.issue_key.exclude(finish_time__isnull=True)
        total_millis = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_millis / (1000 * 60 * 60), 2)  # Convert ms to hours

    class Meta:
        model = CncTask
        fields = [
            'key', 'machine_fk', 'machine_name', 'name', 'nesting_id', 'material', 'dimensions', 'quantity',
            'thickness_mm', 'completion_date', 'completed_by', 'completed_by_username', 'estimated_hours', 'total_hours_spent', 'parts_count', 'in_plan', 'plan_order', 'plan_order'
        ]


class CncTaskDetailSerializer(serializers.ModelSerializer):
    """
    A detailed serializer for a single CncTask instance.
    Handles creation (with nested parts), retrieval, and updates.
    Includes the 'nesting_file' upload and the full list of nested 'parts'.
    """
    # Nested serializer for CncPart.
    # 'parts' is the related_name on the CncPart.cnc_task ForeignKey.
    # It's read-only for retrieval (detail view).
    parts = CncPartSerializer(many=True, read_only=True)
    files = TaskFileSerializer(many=True, read_only=True)
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    selected_plate = NullablePKRelatedField(
        queryset=RemnantPlate.objects.all(),
        required=False, allow_null=True
    )

    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'nesting_id', 'material', 'dimensions', 'selected_plate',
            'thickness_mm', 'parts', 'files', 'machine_fk', 'machine_name', 'estimated_hours', 'quantity'
        ]
        read_only_fields = ['key']
        extra_kwargs = {
            # No file field here anymore, it's handled manually
        }

    def create(self, validated_data):
        # Manually get 'parts_data' from the initial request data.
        # This bypasses the serializer field validation, which is the source of the issue.
        parts_data_str = self.initial_data.get('parts_data')
        parts_data = []
        if parts_data_str and isinstance(parts_data_str, str):
            try:
                parts_data = json.loads(parts_data_str)
            except json.JSONDecodeError:
                raise serializers.ValidationError({"parts_data": "Invalid JSON format."})

        # Manually get uploaded files from the initial request data.
        # 'files' is the key your frontend will use to send the list of files.
        uploaded_files = self.context['request'].FILES.getlist('files')

        # Generate a unique key if one isn't provided, similar to machining tasks.
        if 'key' not in validated_data or not validated_data['key']:
            with transaction.atomic():
                try:
                    counter, _ = TaskKeyCounter.objects.get_or_create(prefix="CNC")
                except IntegrityError:
                    counter = TaskKeyCounter.objects.get(prefix="CNC")

                next_key_number = counter.current + 1
                counter.current = next_key_number
                counter.save()
                validated_data['key'] = f"CNC-{next_key_number:03d}"

        cnc_task = CncTask.objects.create(**validated_data)

        # Use bulk_create for performance when creating multiple parts.
        CncPart.objects.bulk_create([CncPart(cnc_task=cnc_task, **part_data) for part_data in parts_data])

        # Create TaskFile objects for each uploaded file.
        task_files_to_create = [
            TaskFile(task=cnc_task, file=file, uploaded_by=self.context['request'].user)
            for file in uploaded_files
        ]
        if task_files_to_create:
            TaskFile.objects.bulk_create(task_files_to_create)

        return cnc_task
    
    def update(self, instance, validated_data):
        # Pull selected_plate explicitly so we can clear it if provided as None/empty
        selected_plate = validated_data.pop('selected_plate', serializers.empty)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if selected_plate is not serializers.empty:
            # Can be an instance or None (to remove)
            instance.selected_plate = selected_plate

        instance.save()
        return instance


class CncHoldTaskSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for listing CNC hold tasks.
    """
    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'nesting_id'
        ]
        read_only_fields = ['key', 'name', 'nesting_id']


class RemnantPlateSerializer(serializers.ModelSerializer):
    """
    Serializer for the RemnantPlate model.
    """
    class Meta:
        model = RemnantPlate
        fields = ['id', 'thickness_mm', 'thickness_mm_2', 'dimensions', 'quantity', 'material']


# --- Planning Serializers ---

class CncPlanningListItemSerializer(serializers.ModelSerializer):
    """
    Serializer for listing CNC tasks in a planning view. Includes calculated fields.
    """
    total_hours_spent = serializers.SerializerMethodField()
    remaining_hours = serializers.SerializerMethodField()

    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'nesting_id', 'material', 'dimensions',
            'thickness_mm', 'in_plan', 'plan_order', 'plan_locked',
            'planned_start_ms', 'planned_end_ms', 'estimated_hours',
            'total_hours_spent', 'remaining_hours', 'machine_fk'
        ]

    # Sum finished timers (epoch-ms → hours)
    def _sum_timer_hours(self, obj: CncTask) -> float:
        # Use the reverse generic relation
        qs = obj.issue_key.exclude(finish_time__isnull=True).only('start_time', 'finish_time')
        total_ms = 0
        for t in qs:
            if t.start_time is None:
                continue
            end = t.finish_time
            if end is None or end <= t.start_time:
                continue
            total_ms += (end - t.start_time)
        return round(total_ms / 3_600_000.0, 2)

    def get_total_hours_spent(self, obj):
        return self._sum_timer_hours(obj)

    def get_remaining_hours(self, obj):
        est = float(obj.estimated_hours or 0)
        spent = self._sum_timer_hours(obj)
        return round(max(0.0, est - spent), 2)


class CncProductionPlanSerializer(serializers.ModelSerializer):
    """
    Serializer for the production plan view, which may include additional fields
    like the first time a timer was started for the task.
    """
    first_timer_start = serializers.IntegerField(read_only=True)

    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'in_plan', 'plan_order', 'plan_locked',
            'planned_start_ms', 'planned_end_ms', 'estimated_hours',
            'first_timer_start', 'machine_fk'
        ]


class CncTaskPlanUpdateItemSerializer(serializers.ModelSerializer):
    """
    Serializer for validating a single item in a bulk planning update.
    It allows partial updates.
    """
    key = serializers.CharField()
    machine_fk = serializers.PrimaryKeyRelatedField(
        queryset=Machine.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = CncTask
        fields = [
            'key', 'in_plan', 'machine_fk', 'planned_start_ms',
            'planned_end_ms', 'plan_order', 'plan_locked'
        ]
        extra_kwargs = {
            'in_plan': {'required': False},
            'planned_start_ms': {'required': False},
            'planned_end_ms': {'required': False},
            'plan_order': {'required': False, 'allow_null': True},
            'plan_locked': {'required': False},
        }


class CncTaskPlanBulkListSerializer(serializers.ListSerializer):
    """
    List serializer to handle bulk updates and validations for CNC task planning.
    """
    def update(self, instances, validated_data):
        instance_map = {instance.key: instance for instance in instances}
        result = []
        for data in validated_data:
            instance = instance_map.get(data['key'])
            if instance:
                # This is a simplified update. The generic view handles the logic.
                result.append(self.child.update(instance, data))
        return result