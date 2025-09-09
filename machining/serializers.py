from rest_framework import serializers
from .models import Task, TaskKeyCounter, Timer
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

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
            'completion_date', 'completed_by', 'completed_by_username', 'estimated_hours', 'total_hours_spent', 'machine_fk', 'finish_time', 'machine_name',
            'planned_start_ms', 'planned_end_ms', 'plan_order', 'plan_locked'
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


class MachinePlanSegmentSerializer(serializers.Serializer):
    start_ms   = serializers.IntegerField()
    end_ms     = serializers.IntegerField()
    task_key   = serializers.CharField()
    task_name  = serializers.CharField(allow_null=True)
    is_hold    = serializers.BooleanField()
    category   = serializers.CharField()            # always "planned" here
    plan_order = serializers.IntegerField(allow_null=True)
    plan_locked = serializers.BooleanField()
    machine_id  = serializers.IntegerField()

class TaskPlanUpdateItemSerializer(serializers.ModelSerializer):
    key = serializers.CharField()

    class Meta:
        model = Task
        fields = ['key', 'machine_fk', 'planned_start_ms', 'planned_end_ms', 'plan_order', 'plan_locked']
        extra_kwargs = {
            'machine_fk': {'required': False, 'allow_null': True},
            'planned_start_ms': {'required': False, 'allow_null': True},
            'planned_end_ms': {'required': False, 'allow_null': True},
            'plan_order': {'required': False, 'allow_null': True},
            'plan_locked': {'required': False},
        }

class TaskPlanBulkListSerializer(serializers.ListSerializer):
    child = TaskPlanUpdateItemSerializer()

    def validate(self, data):
        # Ensure (machine_fk, plan_order) uniqueness inside this payload
        seen = set()
        for item in data:
            plan_order = item.get('plan_order')
            # fallback to current machine if not provided
            if 'machine_fk' in item and item['machine_fk'] is not None:
                machine_id = item['machine_fk'].id if hasattr(item['machine_fk'], 'id') else item['machine_fk']
            else:
                cur = Task.objects.only('machine_fk_id').get(pk=item['key'])
                machine_id = cur.machine_fk_id
            if plan_order is not None and machine_id:
                key = (machine_id, plan_order)
                if key in seen:
                    raise serializers.ValidationError(f'duplicate plan_order {plan_order} for machine {machine_id}')
                seen.add(key)
        return data

    def update(self, instances, validated_data):
        by_key = {row['key']: row for row in validated_data}
        qs = Task.objects.filter(key__in=by_key.keys()).select_for_update()
        updated = []
        for obj in qs:
            payload = by_key[obj.key]
            for f in ['machine_fk', 'planned_start_ms', 'planned_end_ms', 'plan_order', 'plan_locked']:
                if f in payload:
                    setattr(obj, f, payload[f])
            obj.save(update_fields=[f for f in ['machine_fk','planned_start_ms','planned_end_ms','plan_order','plan_locked'] if f in payload])
            updated.append(obj)
        return updated

class TaskPlanBulkWrapperSerializer(serializers.Serializer):
    items = TaskPlanBulkListSerializer()


class MachineTimelineSegmentSerializer(serializers.Serializer):
    start_ms   = serializers.IntegerField()
    end_ms     = serializers.IntegerField()
    task_key   = serializers.CharField(allow_null=True)
    task_name  = serializers.CharField(allow_null=True)
    is_hold    = serializers.BooleanField()
    category   = serializers.CharField()


class PlanningCandidateSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True)
    total_hours_spent = serializers.SerializerMethodField()
    remaining_hours = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'key', 'name', 'job_no', 'image_no', 'position_no', 'quantity',
            'estimated_hours', 'total_hours_spent', 'remaining_hours',
            'machine_fk', 'machine_name', 'finish_time', 'is_hold_task',
        ]

    def get_total_hours_spent(self, obj):
        # same logic you already use in TaskSerializer
        timers = obj.timers.exclude(finish_time__isnull=True)
        total_millis = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_millis / (1000 * 60 * 60), 2)

    def get_remaining_hours(self, obj):
        est = float(obj.estimated_hours or 0)
        return max(0.0, round(est - self.get_total_hours_spent(obj), 2))