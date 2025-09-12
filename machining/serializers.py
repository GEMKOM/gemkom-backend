from rest_framework import serializers

from machines.calendar import validate_plan_interval
from machines.models import Machine
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


class PlanningListItemSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True)
    total_hours_spent = serializers.SerializerMethodField()
    remaining_hours = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            # identity
            'key', 'name', 'job_no', 'image_no', 'position_no', 'quantity',
            # machine
            'machine_fk', 'machine_name',
            # plan state
            'in_plan', 'planned_start_ms', 'planned_end_ms', 'plan_order', 'plan_locked',
            # hours
            'estimated_hours', 'total_hours_spent', 'remaining_hours',
            # useful for initial auto-sort
            'finish_time',
        ]

    # Sum finished timers (epoch-ms → hours)
    def _sum_timer_hours(self, obj: Task) -> float:
        qs = Timer.objects.filter(issue_key=obj).exclude(finish_time__isnull=True).only('start_time', 'finish_time')
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


# ----------------------------
# Planning: bulk save payload
# ----------------------------
class TaskPlanUpdateItemSerializer(serializers.ModelSerializer):
    # Your Task PK is "key" (string)
    key = serializers.CharField()

    class Meta:
        model = Task
        fields = [
            'key', 'machine_fk',
            'planned_start_ms', 'planned_end_ms',
            'plan_order', 'plan_locked',
            'in_plan',
        ]
        extra_kwargs = {
            'machine_fk': {'required': False, 'allow_null': True},
            'planned_start_ms': {'required': False, 'allow_null': True},
            'planned_end_ms': {'required': False, 'allow_null': True},
            'plan_order': {'required': False, 'allow_null': True},
            'plan_locked': {'required': False},
            'in_plan': {'required': False},
        }

class TaskPlanBulkListSerializer(serializers.ListSerializer):
    child = TaskPlanUpdateItemSerializer()

    def validate(self, data):
        errors = []
        seen = set()

        for item in data:
            in_plan = item.get('in_plan', True)

            # uniqueness among in-plan items (existing code of yours)
            order = item.get('plan_order')
            if in_plan and order is not None:
                if 'machine_fk' in item and item['machine_fk'] is not None:
                    machine_id = item['machine_fk'].id if hasattr(item['machine_fk'], 'id') else item['machine_fk']
                else:
                    machine_id = Task.objects.only('machine_fk_id').get(pk=item['key']).machine_fk_id
                k = (machine_id, order)
                if k in seen:
                    raise serializers.ValidationError(f'duplicate plan_order {order} for machine {machine_id} among in-plan items')
                seen.add(k)

            # calendar validation only if both times supplied and in_plan
            if in_plan and item.get('planned_start_ms') is not None and item.get('planned_end_ms') is not None:
                if 'machine_fk' in item and item['machine_fk'] is not None:
                    machine = item['machine_fk'] if hasattr(item['machine_fk'], 'id') else Machine.objects.get(pk=item['machine_fk'])
                else:
                    machine = Task.objects.select_related('machine_fk').get(pk=item['key']).machine_fk

        if errors:
            raise serializers.ValidationError({"calendar": errors})
        return data

    def update(self, instances, validated_data):
        # instances is a list matching validated_data order
        # Map existing instances by key for safety
        by_key = {obj.key: obj for obj in instances}
        updated = []
        for row in validated_data:
            obj = by_key[row['key']]
            for f in ['machine_fk','planned_start_ms','planned_end_ms','plan_order','plan_locked','in_plan']:
                if f in row:
                    setattr(obj, f, row[f])
            obj.save(update_fields=[f for f in ['machine_fk','planned_start_ms','planned_end_ms','plan_order','plan_locked','in_plan'] if f in row])
            updated.append(obj)
        return updated

class TaskPlanUpdateItemSerializer(serializers.ModelSerializer):
    key = serializers.CharField()

    class Meta:
        model = Task
        fields = ['key','machine_fk','planned_start_ms','planned_end_ms','plan_order','plan_locked','in_plan']
        extra_kwargs = {
            'machine_fk': {'required': False, 'allow_null': True},
            'planned_start_ms': {'required': False, 'allow_null': True},
            'planned_end_ms': {'required': False, 'allow_null': True},
            'plan_order': {'required': False, 'allow_null': True},
            'plan_locked': {'required': False},
            'in_plan': {'required': False},
        }
        # 👇 THIS is the key line
        list_serializer_class = TaskPlanBulkListSerializer


# ----------------------------
# Analytics: machine timeline segments (actuals & idle)
# ----------------------------
class MachineTimelineSegmentSerializer(serializers.Serializer):
    start_ms  = serializers.IntegerField()
    end_ms    = serializers.IntegerField()
    task_key  = serializers.CharField(allow_null=True)
    task_name = serializers.CharField(allow_null=True)
    is_hold   = serializers.BooleanField()
    category  = serializers.CharField()  # "work" | "hold" | "idle"