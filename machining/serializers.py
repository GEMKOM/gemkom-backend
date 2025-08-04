from rest_framework import serializers
from .models import Task, TaskKeyCounter, Timer
from django.db import transaction

class TimerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    stopped_by_first_name = serializers.CharField(source='stopped_by.first_name', read_only=True)
    stopped_by_last_name = serializers.CharField(source='stopped_by.last_name', read_only=True)
    issue_name = serializers.CharField(source='issue_key.name', read_only=True)
    issue_is_hold_task = serializers.BooleanField(source='issue_key.is_hold_task', read_only=True)
    job_no = serializers.CharField(source='issue_key.job_no', read_only=True)
    image_no = serializers.CharField(source='issue_key.image_no', read_only=True)
    position_no = serializers.CharField(source='issue_key.position_no', read_only=True)
    quantity = serializers.IntegerField(source='issue_key.quantity', read_only=True)
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True)  # ✅ add this line
    duration = serializers.FloatField(read_only=True)

    class Meta:
        model = Timer
        fields = [
            'id',
            'user',
            'username',
            'issue_key',
            'start_time',
            'finish_time',
            'comment',
            'machine_fk',        # This will now be the machine FK ID
            'machine_name',    # ✅ Human-readable name
            'issue_name',
            'issue_is_hold_task',
            'job_no',
            'image_no',
            'position_no',
            'quantity',
            'manual_entry',
            'stopped_by',
            'stopped_by_first_name',
            'stopped_by_last_name',
            'duration',
        ]
        read_only_fields = ['id', 'user']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
    
class TaskSerializer(serializers.ModelSerializer):
    key = serializers.CharField(required=False)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True)
    total_hours_spent = serializers.SerializerMethodField()
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True)  # ✅ add this line
    

    class Meta:
        model = Task
        fields = [
            'key', 'name', 'job_no', 'image_no', 'position_no', 'quantity',
            'completion_date', 'completed_by', 'completed_by_username', 'estimated_hours', 'total_hours_spent', 'machine_fk', 'finish_time', 'machine_name'
        ]
        read_only_fields = ['completed_by', 'completion_date']

    def get_total_hours_spent(self, obj):
        timers = obj.timers.exclude(finish_time__isnull=True)
        total_millis = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_millis / (1000 * 60 * 60), 2)  # Convert ms to hours
    
    def create(self, validated_data):
        if 'key' not in validated_data or not validated_data['key']:
            with transaction.atomic():
                counter = TaskKeyCounter.objects.select_for_update().get(prefix="TI")
                next_key_number = counter.current + 1
                counter.current = next_key_number
                counter.save()
                validated_data['key'] = f"TI-{next_key_number:03d}"

        return super().create(validated_data)


class HoldTaskSerializer(serializers.ModelSerializer):

    class Meta:
        model = Task
        fields = [
            'key', 'name', 'job_no'
        ]
        read_only_fields = ['key', 'name', 'job_no']