import json
from rest_framework import serializers
from .models import CncTask, CncPart
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
        fields = ['id', 'cnc_task', 'job_no', 'image_no', 'position_no', 'weight_kg']


class CncTimerSerializer(BaseTimerSerializer):
    """
    Extends the BaseTimerSerializer to include fields specific to a CncTask.
    """
    nesting_id = serializers.CharField(source='issue_key.nesting_id', read_only=True)
    material = serializers.CharField(source='issue_key.material', read_only=True)

    class Meta(BaseTimerSerializer.Meta):
        # Inherit fields from the base and add the new ones
        fields = BaseTimerSerializer.Meta.fields + [
            'nesting_id', 'material'
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
            'key', 'machine_fk', 'machine_name', 'name', 'nesting_id', 'material', 'dimensions',
            'thickness_mm', 'completion_date', 'completed_by', 'completed_by_username', 'estimated_hours', 'total_hours_spent', 'parts_count',
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

    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'nesting_id', 'material', 'dimensions',
            'thickness_mm', 'parts', 'files', 'machine_fk', 'machine_name', 'estimated_hours'
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
