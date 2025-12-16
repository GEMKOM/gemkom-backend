from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType

from .models import Timer, TaskFile


class TaskFileSerializer(serializers.ModelSerializer):
    """
    Serializer for the generic TaskFile model.
    """
    file_url = serializers.URLField(source='file.url', read_only=True)
    file_name = serializers.CharField(source='file.name', read_only=True)
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)

    class Meta:
        model = TaskFile
        fields = ['id', 'file_url', 'file_name', 'uploaded_at', 'uploaded_by_username']


class BaseTimerSerializer(serializers.ModelSerializer):
    # --- Fields for reading a Timer ---
    username = serializers.CharField(source='user.username', read_only=True)
    stopped_by_first_name = serializers.CharField(source='stopped_by.first_name', read_only=True)
    stopped_by_last_name = serializers.CharField(source='stopped_by.last_name', read_only=True)
    issue_name = serializers.CharField(source='issue_key.name', read_only=True)
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True)
    duration = serializers.FloatField(read_only=True)
    task_total_hours = serializers.FloatField(read_only=True)

    # --- Fields for creating/updating a Timer with a Generic Foreign Key ---
    task_key = serializers.CharField(write_only=True, source='object_id')
    task_type = serializers.ChoiceField(write_only=True, choices=['machining', 'cnc_cutting'])

    class Meta:
        model = Timer
        fields = [
            'id', 'user', 'username', 'issue_key', 'task_key', 'task_type',
            'start_time', 'finish_time', 'comment', 'machine_fk', 'machine_name', 'issue_name',
            'manual_entry', 'stopped_by', 'stopped_by_first_name', 'stopped_by_last_name', 'duration',
            'task_total_hours',
        ]
        read_only_fields = ['id', 'user', 'issue_key']

    def create(self, validated_data):
        from django.db import IntegrityError

        validated_data['user'] = self.context['request'].user

        task_type_name = validated_data.pop('task_type')
        # This logic determines which model to link to based on the task_type
        app_label = 'machining' if task_type_name == 'machining' else 'cnc_cutting'
        model_name = 'task' if task_type_name == 'machining' else 'cnctask'

        try:
            content_type = ContentType.objects.get(app_label=app_label, model=model_name)
            validated_data['content_type'] = content_type
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(f"Invalid task_type: {task_type_name}")

        # Check for existing active timer before creating
        user = validated_data['user']
        machine_fk = validated_data.get('machine_fk')
        object_id = validated_data.get('object_id')

        existing_timer = Timer.objects.filter(
            user=user,
            machine_fk=machine_fk,
            content_type=content_type,
            object_id=object_id,
            finish_time__isnull=True
        ).first()

        if existing_timer:
            raise serializers.ValidationError({
                'detail': 'An active timer already exists for this user, machine, and task combination.',
                'existing_timer_id': existing_timer.id
            })

        try:
            return super().create(validated_data)
        except IntegrityError as e:
            # Catch database constraint violation for additional safety
            if 'unique_active_timer_per_user_machine_task' in str(e):
                raise serializers.ValidationError({
                    'detail': 'An active timer already exists for this user, machine, and task combination.'
                })
            raise

    def to_representation(self, instance):
        # When reading a timer, we want the 'issue_key' field to contain the
        # actual primary key of the related task (e.g., "TI-123").
        ret = super().to_representation(instance)
        if instance.issue_key:
            ret['issue_key'] = instance.issue_key.pk
        return ret
