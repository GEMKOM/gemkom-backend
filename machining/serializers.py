from rest_framework import serializers
from .models import Task
from tasks.models import TaskKeyCounter 
from tasks.serializers import BaseTimerSerializer
from django.db import transaction


class TimerSerializer(BaseTimerSerializer):
    """
    Extends the BaseTimerSerializer to include fields specific to a Machining Task.
    """
    issue_is_hold_task = serializers.BooleanField(source='issue_key.is_hold_task', read_only=True)
    job_no = serializers.CharField(source='issue_key.job_no', read_only=True)
    image_no = serializers.CharField(source='issue_key.image_no', read_only=True)
    position_no = serializers.CharField(source='issue_key.position_no', read_only=True)
    quantity = serializers.IntegerField(source='issue_key.quantity', read_only=True)
    estimated_hours = serializers.DecimalField(source='issue_key.estimated_hours', read_only=True, max_digits=10, decimal_places=2)

    class Meta(BaseTimerSerializer.Meta):
        # Inherit fields from the base and add the new ones
        fields = BaseTimerSerializer.Meta.fields + [
            'issue_is_hold_task', 'job_no', 'image_no', 'position_no', 'quantity', 'estimated_hours'
        ]

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
            'in_plan', 'planned_start_ms', 'planned_end_ms', 'plan_order'
        ]
        read_only_fields = ['completed_by', 'completion_date']
        validators = []


    def validate(self, attrs):
        instance = getattr(self, 'instance', None)

        # If machine changes, unplan this task (your rule)
        if instance and 'machine_fk' in attrs and attrs['machine_fk'] != instance.machine_fk:
            attrs['in_plan'] = False
            attrs['plan_order'] = None
            attrs['planned_start_ms'] = None
            attrs['planned_end_ms'] = None

        # ✅ Only enforce unique constraint if still planned
        in_plan = attrs.get('in_plan', getattr(instance, 'in_plan', False))
        machine_fk = attrs.get('machine_fk', getattr(instance, 'machine_fk', None))
        plan_order = attrs.get('plan_order', getattr(instance, 'plan_order', None))

        if in_plan and plan_order is not None and machine_fk is not None:
            qs = Task.objects.filter(
                machine_fk=machine_fk,
                plan_order=plan_order,
                in_plan=True,
            )
            if instance is not None:
                qs = qs.exclude(pk=instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    "plan_order": "Bu makinede aynı plan sırası zaten kullanılıyor (in_plan=True iken benzersiz olmalı)."
                })

        return attrs

    def get_total_hours_spent(self, obj):
        # Use the reverse generic relation. Django automatically provides this.
        # The related_name on the GFK is 'issue_key'.
        timers = obj.issue_key.exclude(finish_time__isnull=True)
        total_millis = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_millis / (1000 * 60 * 60), 2)  # Convert ms to hours
    
    def create(self, validated_data):
        if 'key' not in validated_data or not validated_data['key']:
            with transaction.atomic():
                # Use the generic TaskKeyCounter from the 'tasks' app
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
            'completion_date'
        ]

    # Sum finished timers (epoch-ms → hours)
    def _sum_timer_hours(self, obj: Task) -> float:
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
    

class ProductionPlanSerializer(serializers.ModelSerializer):
    total_hours_spent = serializers.SerializerMethodField()
    actual_start_ms = serializers.IntegerField(source='first_timer_start', read_only=True)

    class Meta:
        model = Task
        fields = [
            # identity
            'key', 'name', 'job_no', 'planned_start_ms', 
            'planned_end_ms', 'estimated_hours', 'total_hours_spent', 
            'completion_date', 'actual_start_ms'
        ]

    # Sum finished timers (epoch-ms → hours)
    def _sum_timer_hours(self, obj: Task) -> float:
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


class TaskPlanBulkListSerializer(serializers.ListSerializer):
    """
    Bulk updates for existing tasks only (no creates).
    - Enforces (machine_fk, plan_order) uniqueness among in-payload rows.
    - Optional calendar hook left in place.
    - If in_plan is False -> clear planning fields.
    - Efficient bulk_update.
    """

    def validate(self, data):
        errors = []
        seen_pairs = set()
        seen_keys = set()
        existing_machine_map = (self.context or {}).get("existing_machine_map", {})

        for item in data:
            key = item["key"]
            if key in seen_keys:
                errors.append({"key": key, "error": "duplicate key in payload"})
            seen_keys.add(key)

            in_plan = item.get('in_plan', True)
            order = item.get('plan_order')

            # Uniqueness within the payload for (machine, plan_order)
            if in_plan and order is not None:
                if 'machine_fk' in item and item['machine_fk'] is not None:
                    machine_id = item['machine_fk'].id if hasattr(item['machine_fk'], 'id') else item['machine_fk']
                else:
                    machine_id = existing_machine_map.get(key)  # fallback to existing machine

                if machine_id is not None:
                    pair = (machine_id, order)
                    if pair in seen_pairs:
                        errors.append({"key": key, "error": f"duplicate plan_order {order} for machine {machine_id} in payload"})
                    else:
                        seen_pairs.add(pair)

            # calendar overlap hook (optional)
            # if in_plan and item.get('planned_start_ms') is not None and item.get('planned_end_ms') is not None:
            #     ...

        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data

    @transaction.atomic
    def update(self, instances, validated_data):
        inst_by_key = {obj.key: obj for obj in instances}

        # Build an "intent" map so we know the final target of each item
        intent = {}  # key -> dict of final values we will apply in phase 2
        to_remove = []  # tasks to remove from plan outright (phase 2 only)

        def _get_machine_id(val, cur):
            if val is None:
                return cur.machine_fk_id
            return getattr(val, "id", val)

        for row in validated_data:
            obj = inst_by_key[row['key']]
            # If explicit remove from plan
            if row.get('in_plan') is False:
                to_remove.append(obj.key)
                continue

            final = {
                "in_plan": row.get('in_plan', obj.in_plan),
                "machine_fk_id": _get_machine_id(row.get('machine_fk'), obj),
                "planned_start_ms": row.get('planned_start_ms', obj.planned_start_ms),
                "planned_end_ms": row.get('planned_end_ms', obj.planned_end_ms),
                "plan_order": row.get('plan_order', obj.plan_order),
                "plan_locked": row.get('plan_locked', obj.plan_locked),
                "name": row.get('name', obj.name),
            }
            intent[obj.key] = final

        # -----------------------------
        # PHASE 1: neutralize conflicts
        # -----------------------------
        # Any task that will occupy a (machine, plan_order) slot should have its current
        # plan_order cleared first, so we don't hit the unique constraint when swapping.
        phase1 = []
        for key, final in intent.items():
            obj = inst_by_key[key]

            # Only neutralize tasks that will be "in plan" with a concrete order
            if final["in_plan"] and final["plan_order"] is not None:
                # If it already has an order (even the same), clear it first
                if obj.plan_order is not None:
                    obj.plan_order = None
                    phase1.append(obj)

        # Also neutralize tasks that are being removed from plan? Not necessary for uniqueness,
        # but harmless; we can do it directly in phase 2.

        if phase1:
            Task.objects.bulk_update(phase1, ["plan_order"])

        # -----------------------------
        # PHASE 2: apply final states
        # -----------------------------
        phase2 = []
        fields2 = set()

        def set_if_changed(obj, field, value):
            if getattr(obj, field) != value:
                setattr(obj, field, value)
                fields2.add(field)

        # 2a) removals from plan
        for key in to_remove:
            obj = inst_by_key[key]
            set_if_changed(obj, 'in_plan', False)
            set_if_changed(obj, 'machine_fk_id', None)
            set_if_changed(obj, 'planned_start_ms', None)
            set_if_changed(obj, 'planned_end_ms', None)
            set_if_changed(obj, 'plan_order', None)
            set_if_changed(obj, 'plan_locked', False)
            phase2.append(obj)

        # 2b) intended finals
        for key, final in intent.items():
            obj = inst_by_key[key]
            # apply final fields
            set_if_changed(obj, 'in_plan', final['in_plan'])
            set_if_changed(obj, 'machine_fk_id', final['machine_fk_id'])
            set_if_changed(obj, 'planned_start_ms', final['planned_start_ms'])
            set_if_changed(obj, 'planned_end_ms', final['planned_end_ms'])
            set_if_changed(obj, 'plan_order', final['plan_order'])
            set_if_changed(obj, 'plan_locked', final['plan_locked'])
            set_if_changed(obj, 'name', final['name'])
            phase2.append(obj)

        if phase2 and fields2:
            Task.objects.bulk_update(phase2, list(fields2))

        return list(inst_by_key.values())

class TaskPlanUpdateItemSerializer(serializers.ModelSerializer):
    key = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Task
        fields = ["key","name","machine_fk","planned_start_ms","planned_end_ms","plan_order","plan_locked","in_plan"]
        list_serializer_class = TaskPlanBulkListSerializer
        extra_kwargs = {
            "machine_fk": {"required": False, "allow_null": True},
            "planned_start_ms": {"required": False, "allow_null": True},
            "planned_end_ms": {"required": False, "allow_null": True},
            "plan_order": {"required": False, "allow_null": True},
            "plan_locked": {"required": False},
            "in_plan": {"required": False},
        }
        # Disable per-item UniqueTogetherValidator; we enforce uniqueness at list-level + DB constraint.
        validators = []

    def validate(self, attrs):
        # Pair-wise start/end logic (what you already had)
        start_provided = 'planned_start_ms' in attrs
        end_provided   = 'planned_end_ms' in attrs

        start_val = attrs.get('planned_start_ms', getattr(self.instance, 'planned_start_ms', None))
        end_val   = attrs.get('planned_end_ms',   getattr(self.instance, 'planned_end_ms',   None))

        if start_provided ^ end_provided:
            raise serializers.ValidationError("planned_start_ms and planned_end_ms must be provided together (or both omitted).")

        if start_provided and end_provided and start_val is not None and end_val is not None:
            if not isinstance(start_val, int) or not isinstance(end_val, int):
                raise serializers.ValidationError("planned_start_ms and planned_end_ms must be integers (epoch ms).")
            if start_val > end_val:
                raise serializers.ValidationError("planned_start_ms cannot be after planned_end_ms.")

        return attrs


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
