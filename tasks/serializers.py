from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum, Q, ExpressionWrapper, FloatField, Value
from django.db.models.functions import Coalesce

from .models import Timer, TaskFile, Part, Tool, Operation, OperationTool, TaskKeyCounter
from machines.models import Machine


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
    task_type = serializers.ChoiceField(write_only=True, choices=['machining', 'cnc_cutting', 'operation'])

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
        if task_type_name == 'machining':
            app_label = 'machining'
            model_name = 'task'
        elif task_type_name == 'cnc_cutting':
            app_label = 'cnc_cutting'
            model_name = 'cnctask'
        elif task_type_name == 'operation':
            app_label = 'tasks'
            model_name = 'operation'
        else:
            raise serializers.ValidationError(f"Invalid task_type: {task_type_name}")

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


class OperationTimerSerializer(BaseTimerSerializer):
    """
    Timer serializer for Operations (migrated from machining tasks).
    Gets job info from operation.part instead of directly from the operation.
    """
    # For backward compatibility, include the same fields as machining TimerSerializer
    issue_is_hold_task = serializers.SerializerMethodField()
    job_no = serializers.CharField(source='issue_key.part.job_no', read_only=True)
    image_no = serializers.CharField(source='issue_key.part.image_no', read_only=True)
    position_no = serializers.CharField(source='issue_key.part.position_no', read_only=True)
    quantity = serializers.IntegerField(source='issue_key.part.quantity', read_only=True)
    estimated_hours = serializers.DecimalField(source='issue_key.estimated_hours', read_only=True, max_digits=10, decimal_places=2)

    def get_issue_is_hold_task(self, obj):  # noqa: ARG002
        # Operations don't have is_hold_task, always return False
        return False

    class Meta(BaseTimerSerializer.Meta):
        fields = BaseTimerSerializer.Meta.fields + [
            'issue_is_hold_task', 'job_no', 'image_no', 'position_no', 'quantity', 'estimated_hours'
        ]


# ==================== Part-Operation System Serializers ====================


class ToolSerializer(serializers.ModelSerializer):
    """Serializer for Tool model with availability tracking"""
    available_quantity = serializers.SerializerMethodField()
    in_use_count = serializers.SerializerMethodField()

    class Meta:
        model = Tool
        fields = [
            'id', 'code', 'name', 'description', 'category',
            'quantity', 'available_quantity', 'in_use_count',
            'is_active', 'properties', 'created_at', 'updated_at'
        ]

    def get_available_quantity(self, obj):
        return obj.get_available_quantity()

    def get_in_use_count(self, obj):
        return obj.get_in_use_count()


class OperationToolSerializer(serializers.ModelSerializer):
    """Serializer for OperationTool junction model"""
    tool_code = serializers.CharField(source='tool.code', read_only=True)
    tool_name = serializers.CharField(source='tool.name', read_only=True)

    class Meta:
        model = OperationTool
        fields = ['id', 'tool', 'tool_code', 'tool_name', 'quantity', 'notes', 'display_order']


class OperationSerializer(serializers.ModelSerializer):
    """Serializer for Operation model"""
    part_key = serializers.CharField(source='part.key', read_only=True)
    part_name = serializers.CharField(source='part.name', read_only=True)
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True, allow_null=True)
    operation_tools = OperationToolSerializer(many=True, read_only=True)
    total_hours_spent = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, default=0
    )

    class Meta:
        model = Operation
        fields = [
            'key', 'name', 'description', 'part_key', 'part_name', 'order', 'interchangeable',
            'machine_fk', 'machine_name',
            'estimated_hours', 'total_hours_spent',
            'in_plan', 'plan_order', 'planned_start_ms', 'planned_end_ms', 'plan_locked',
            'created_by', 'created_by_username', 'created_at',
            'completed_by', 'completed_by_username', 'completion_date',
            'operation_tools'
        ]
        read_only_fields = ['key', 'created_by', 'created_at', 'completed_by', 'completion_date']

    def validate(self, attrs):
        # Order validation for completion
        if self.instance and 'completion_date' in attrs and attrs.get('completion_date'):
            if not self.instance.interchangeable:
                # Check previous operations
                previous_incomplete = Operation.objects.filter(
                    part=self.instance.part,
                    order__lt=self.instance.order,
                    completion_date__isnull=True
                )
                if previous_incomplete.exists():
                    raise serializers.ValidationError(
                        "All previous operations must be completed first"
                    )
        return attrs


class OperationDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for engineers/management.
    Includes full part information, tools, planning data, and all metadata.
    Used for: list view, retrieve view, and updates.
    """
    part_key = serializers.CharField(source='part.key', read_only=True)
    part_name = serializers.CharField(source='part.name', read_only=True)
    part_job_no = serializers.CharField(source='part.job_no', read_only=True, allow_null=True)
    part_image_no = serializers.CharField(source='part.image_no', read_only=True, allow_null=True)
    part_position_no = serializers.CharField(source='part.position_no', read_only=True, allow_null=True)
    part_task_key = serializers.CharField(source='part.task_key', read_only=True, allow_null=True)
    part_quantity = serializers.IntegerField(source='part.quantity', read_only=True, allow_null=True)
    part_completion_date = serializers.IntegerField(source='part.completion_date', read_only=True, allow_null=True)

    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True, allow_null=True)

    operation_tools = OperationToolSerializer(many=True, read_only=True)
    total_hours_spent = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, default=0
    )

    # Include active timer info
    has_active_timer = serializers.SerializerMethodField()

    class Meta:
        model = Operation
        fields = [
            'key', 'name', 'description',
            'part_key', 'part_name', 'part_job_no', 'part_image_no', 'part_position_no', 'part_task_key', 'part_quantity', 'part_completion_date',
            'order', 'interchangeable',
            'machine_fk', 'machine_name',
            'estimated_hours', 'total_hours_spent',
            'in_plan', 'plan_order', 'planned_start_ms', 'planned_end_ms', 'plan_locked',
            'created_by', 'created_by_username', 'created_at',
            'completed_by', 'completed_by_username', 'completion_date',
            'operation_tools', 'has_active_timer'
        ]
        read_only_fields = ['key', 'created_by', 'created_at', 'completed_by', 'completion_date']

    def get_has_active_timer(self, obj):
        """Check if operation has any active timers"""
        return obj.timers.filter(finish_time__isnull=True).exists()

    def validate(self, attrs):
        # Order validation for completion
        if self.instance and 'completion_date' in attrs and attrs.get('completion_date'):
            if not self.instance.interchangeable:
                # Check previous operations
                previous_incomplete = Operation.objects.filter(
                    part=self.instance.part,
                    order__lt=self.instance.order,
                    completion_date__isnull=True
                )
                if previous_incomplete.exists():
                    raise serializers.ValidationError(
                        "All previous operations must be completed first"
                    )
        return attrs


class OperationOperatorSerializer(serializers.ModelSerializer):
    """
    Serializer for operators.
    Includes essential information needed to work on operations:
    - Operation identification and description
    - Full part data (job info, specs, dimensions, material, weight)
    - Machine assignment
    - Tools required
    - Timer-related data

    Excludes: planning fields, creation/completion metadata
    Note: Operations with active timers are filtered out in the ViewSet for list view
    """
    part_key = serializers.CharField(source='part.key', read_only=True)
    part_name = serializers.CharField(source='part.name', read_only=True)
    part_job_no = serializers.CharField(source='part.job_no', read_only=True, allow_null=True)
    part_image_no = serializers.CharField(source='part.image_no', read_only=True, allow_null=True)
    part_position_no = serializers.CharField(source='part.position_no', read_only=True, allow_null=True)
    part_task_key = serializers.CharField(source='part.task_key', read_only=True, allow_null=True)
    part_quantity = serializers.IntegerField(source='part.quantity', read_only=True, allow_null=True)
    part_material = serializers.CharField(source='part.material', read_only=True, allow_null=True)
    part_dimensions = serializers.CharField(source='part.dimensions', read_only=True, allow_null=True)
    part_weight_kg = serializers.DecimalField(
        source='part.weight_kg',
        max_digits=10,
        decimal_places=3,
        read_only=True,
        allow_null=True
    )

    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)

    operation_tools = OperationToolSerializer(many=True, read_only=True)
    total_hours_spent = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, default=0
    )

    class Meta:
        model = Operation
        fields = [
            'key', 'name', 'description',
            'part_key', 'part_name', 'part_job_no', 'part_image_no', 'part_position_no', 'part_task_key',
            'part_quantity', 'part_material', 'part_dimensions', 'part_weight_kg',
            'order',
            'machine_fk', 'machine_name',
            'estimated_hours', 'total_hours_spent',
            'completion_date',
            'operation_tools'
        ]
        read_only_fields = ['key', 'completion_date']


class OperationCreateSerializer(serializers.Serializer):
    """Serializer for creating operations with tools"""
    name = serializers.CharField(max_length=255, required=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    order = serializers.IntegerField()
    machine_fk = serializers.PrimaryKeyRelatedField(
        queryset=Machine.objects.all(), required=True
    )
    interchangeable = serializers.BooleanField(default=False)
    estimated_hours = serializers.DecimalField(max_digits=6, decimal_places=2, required=False, allow_null=True)
    tools = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )

    def create(self, validated_data):
        tools_data = validated_data.pop('tools', [])
        operation = Operation.objects.create(**validated_data)

        # Attach tools
        for tool_id in tools_data:
            OperationTool.objects.create(
                operation=operation,
                tool_id=tool_id
            )

        return operation


class PartSerializer(serializers.ModelSerializer):
    """Serializer for Part model"""
    operations = OperationSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True, allow_null=True)
    has_incomplete_operations = serializers.SerializerMethodField()

    class Meta:
        model = Part
        fields = [
            'key', 'name', 'description',
            'job_no', 'image_no', 'position_no',
            'quantity', 'material', 'dimensions', 'weight_kg',
            'finish_time',
            'created_by', 'created_by_username', 'created_at',
            'completed_by', 'completed_by_username', 'completion_date',
            'operations', 'has_incomplete_operations'
        ]
        read_only_fields = ['key', 'created_by', 'created_at', 'completed_by', 'completion_date']

    def get_has_incomplete_operations(self, obj):
        return obj.operations.filter(completion_date__isnull=True).exists()


class PartWithOperationsSerializer(serializers.ModelSerializer):
    """Serializer for creating Part with nested Operations"""
    operations = OperationCreateSerializer(many=True)

    class Meta:
        model = Part
        fields = [
            'name', 'description', 'job_no', 'image_no', 'position_no',
            'quantity', 'material', 'dimensions', 'weight_kg', 'finish_time',
            'operations'
        ]

    @transaction.atomic
    def create(self, validated_data):
        operations_data = validated_data.pop('operations', [])

        # Generate key using TaskKeyCounter
        with transaction.atomic():
            counter, created = TaskKeyCounter.objects.select_for_update().get_or_create(
                prefix='PT', defaults={'current': 0}
            )
            counter.current += 1
            counter.save()
            part_key = f"PT-{counter.current:03d}"

        # Create part
        import time
        part = Part.objects.create(
            key=part_key,
            created_by=self.context['request'].user,
            created_at=int(time.time() * 1000),
            **validated_data
        )

        # Create operations
        for op_data in operations_data:
            tools_data = op_data.pop('tools', [])

            operation = Operation.objects.create(
                part=part,
                created_by=self.context['request'].user,
                created_at=part.created_at,
                **op_data
            )

            # Attach tools
            for tool_id in tools_data:
                OperationTool.objects.create(
                    operation=operation,
                    tool_id=tool_id
                )

        return part

    def to_representation(self, instance):
        # Use PartSerializer for output to include all related data properly
        return PartSerializer(instance, context=self.context).data


class OperationPlanBulkListSerializer(serializers.ListSerializer):
    """
    Bulk updates for operation planning.
    - Enforces (machine_fk, plan_order) uniqueness among in-payload rows.
    - If in_plan is False -> clear planning fields.
    - Efficient bulk_update with two-phase approach to avoid unique constraint conflicts.
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
                    machine_id = existing_machine_map.get(key)

                if machine_id is not None:
                    pair = (machine_id, order)
                    if pair in seen_pairs:
                        errors.append({"key": key, "error": f"duplicate plan_order {order} for machine {machine_id} in payload"})
                    else:
                        seen_pairs.add(pair)

        if errors:
            raise serializers.ValidationError({"errors": errors})
        return data

    @transaction.atomic
    def update(self, instances, validated_data):
        inst_by_key = {obj.key: obj for obj in instances}

        # Build an "intent" map so we know the final target of each item
        intent = {}
        to_remove = []

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

        # PHASE 1: neutralize conflicts
        phase1 = []
        for key, final in intent.items():
            obj = inst_by_key[key]
            if final["in_plan"] and final["plan_order"] is not None:
                if obj.plan_order is not None:
                    obj.plan_order = None
                    phase1.append(obj)

        if phase1:
            Operation.objects.bulk_update(phase1, ["plan_order"])

        # PHASE 2: apply final states
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
            set_if_changed(obj, 'in_plan', final['in_plan'])
            set_if_changed(obj, 'machine_fk_id', final['machine_fk_id'])
            set_if_changed(obj, 'planned_start_ms', final['planned_start_ms'])
            set_if_changed(obj, 'planned_end_ms', final['planned_end_ms'])
            set_if_changed(obj, 'plan_order', final['plan_order'])
            set_if_changed(obj, 'plan_locked', final['plan_locked'])
            set_if_changed(obj, 'name', final['name'])
            phase2.append(obj)

        if phase2 and fields2:
            Operation.objects.bulk_update(phase2, list(fields2))

        return list(inst_by_key.values())


class OperationPlanUpdateItemSerializer(serializers.ModelSerializer):
    """Serializer for individual operation planning updates"""
    key = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Operation
        fields = ["key", "name", "machine_fk", "planned_start_ms", "planned_end_ms", "plan_order", "plan_locked", "in_plan"]
        list_serializer_class = OperationPlanBulkListSerializer
        extra_kwargs = {
            "machine_fk": {"required": False, "allow_null": True},
            "planned_start_ms": {"required": False, "allow_null": True},
            "planned_end_ms": {"required": False, "allow_null": True},
            "plan_order": {"required": False, "allow_null": True},
            "plan_locked": {"required": False},
            "in_plan": {"required": False},
        }
        validators = []

    def validate(self, attrs):
        # Pair-wise start/end logic
        start_provided = 'planned_start_ms' in attrs
        end_provided = 'planned_end_ms' in attrs

        start_val = attrs.get('planned_start_ms', getattr(self.instance, 'planned_start_ms', None))
        end_val = attrs.get('planned_end_ms', getattr(self.instance, 'planned_end_ms', None))

        if start_provided ^ end_provided:
            raise serializers.ValidationError("planned_start_ms and planned_end_ms must be provided together (or both omitted).")

        if start_provided and end_provided and start_val is not None and end_val is not None:
            if not isinstance(start_val, int) or not isinstance(end_val, int):
                raise serializers.ValidationError("planned_start_ms and planned_end_ms must be integers (epoch ms).")
            if start_val > end_val:
                raise serializers.ValidationError("planned_start_ms cannot be after planned_end_ms.")

        return attrs
