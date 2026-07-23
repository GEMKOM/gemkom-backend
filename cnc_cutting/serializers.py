import json
import re
from decimal import Decimal, InvalidOperation

from core.serializers import NullablePKRelatedField
from rest_framework import serializers

from machines.models import Machine
from .models import CncTask, CncPart, RemnantPlate, RemnantPlateUsage, PLATE_ITEM_CODE_PREFIXES
from tasks.models import TaskKeyCounter, TaskFile
from tasks.serializers import BaseTimerSerializer, TaskFileSerializer
from django.db import transaction
from django.db.utils import IntegrityError
from django.utils import timezone


# Plate item names start with the thickness, e.g. "5 mm ST 37-2 SAC".
# Anchored on purpose: an unanchored search would read "3000" out of
# dimension strings like "1500x3000 mm" and overflow thickness_mm (max 999.99).
PLATE_THICKNESS_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)\s*mm\b', re.IGNORECASE)


def parse_thickness_from_item_name(name):
    """Best-effort thickness (mm) from a plate item name; None when it can't be trusted."""
    if not name:
        return None
    match = PLATE_THICKNESS_RE.match(name)
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(',', '.'))
    except InvalidOperation:
        return None
    if value <= 0 or value >= 1000:
        return None
    return value


def validate_job_no_not_phased(value):
    """
    Reject a job_no that belongs to an engineering job order which has been split
    into production phases. Such jobs must not receive work directly — the work
    belongs on one of the phase job orders (e.g. 270-01/P1) instead.

    Returns the value unchanged when it is safe to use.
    """
    if not value:
        return value
    from projects.models import JobOrder
    phase_nos = list(
        JobOrder.objects
        .filter(source_job_order__job_no=value)
        .order_by('phase_number')
        .values_list('job_no', flat=True)
    )
    if phase_nos:
        raise serializers.ValidationError(
            f"'{value}' iş emri üretim fazlarına bölünmüştür. "
            f"Lütfen şu faz iş emirlerinden birini kullanın: {', '.join(phase_nos)}"
        )
    return value


class CncPartSerializer(serializers.ModelSerializer):
    """
    Serializer for the CncPart model. Used for nested representation
    within a CncTask.
    """
    class Meta:
        model = CncPart
        fields = ['id', 'cnc_task', 'job_no', 'image_no', 'position_no', 'weight_kg', 'quantity']

    def validate_job_no(self, value):
        return validate_job_no_not_phased(value)


class CncPartSearchResultSerializer(serializers.ModelSerializer):
    """
    Serializer for CNC part search results.
    Returns part information along with its parent CNC task details,
    including the plate source (planning item / remnant plate / legacy fields).
    """
    nesting_id = serializers.CharField(source='cnc_task.nesting_id', read_only=True)
    planned_start_ms = serializers.IntegerField(source='cnc_task.planned_start_ms', read_only=True)
    planned_end_ms = serializers.IntegerField(source='cnc_task.planned_end_ms', read_only=True)
    completion_date = serializers.IntegerField(source='cnc_task.completion_date', read_only=True)
    material = serializers.CharField(source='cnc_task.material', read_only=True, allow_null=True)
    thickness_mm = serializers.DecimalField(source='cnc_task.thickness_mm', max_digits=5, decimal_places=2, read_only=True, allow_null=True)
    planning_request_item = serializers.IntegerField(source='cnc_task.planning_request_item_id', read_only=True, allow_null=True)
    plate_item_code = serializers.CharField(source='cnc_task.planning_request_item.item.code', read_only=True, allow_null=True, default=None)
    plate_item_name = serializers.CharField(source='cnc_task.planning_request_item.item.name', read_only=True, allow_null=True, default=None)
    plate_item_is_delivered = serializers.BooleanField(source='cnc_task.planning_request_item.is_delivered', read_only=True, allow_null=True, default=None)
    has_remnant_plate = serializers.SerializerMethodField()

    def get_has_remnant_plate(self, obj):
        return len(obj.cnc_task.plate_usage_records.all()) > 0

    class Meta:
        model = CncPart
        fields = [
            'id', 'job_no', 'image_no', 'position_no', 'weight_kg', 'quantity',
            'nesting_id', 'planned_start_ms', 'planned_end_ms', 'completion_date',
            'material', 'thickness_mm', 'planning_request_item',
            'plate_item_code', 'plate_item_name', 'plate_item_is_delivered',
            'has_remnant_plate'
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


class RemnantPlateSerializer(serializers.ModelSerializer):
    """
    Serializer for the RemnantPlate model.
    """
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = RemnantPlate
        fields = ['id', 'thickness_mm', 'thickness_mm_2', 'dimensions', 'quantity', 'material', 'available_quantity']

    def get_available_quantity(self, obj):
        """Calculate the available quantity for this remnant plate."""
        return obj.available_quantity()


class RemnantPlateUsageSerializer(serializers.ModelSerializer):
    """
    Serializer for RemnantPlateUsage through model.
    Includes nested plate details for reading, and supports creating/updating usage records.
    """
    remnant_plate_details = RemnantPlateSerializer(source='remnant_plate', read_only=True)

    class Meta:
        model = RemnantPlateUsage
        fields = ['id', 'remnant_plate', 'remnant_plate_details', 'quantity_used', 'assigned_date']
        read_only_fields = ['assigned_date']


class CncTaskListSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for listing CncTask instances.
    It excludes the nested 'parts' for performance.
    """
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True)
    total_hours_spent = serializers.SerializerMethodField()
    parts_count = serializers.IntegerField(read_only=True)
    plate_item_code = serializers.CharField(source='planning_request_item.item.code', read_only=True, allow_null=True, default=None)
    plate_item_name = serializers.CharField(source='planning_request_item.item.name', read_only=True, allow_null=True, default=None)
    plate_item_is_delivered = serializers.BooleanField(source='planning_request_item.is_delivered', read_only=True, allow_null=True, default=None)
    plate_item_is_consumed = serializers.BooleanField(source='planning_request_item.is_consumed', read_only=True, allow_null=True, default=None)
    has_remnant_plate = serializers.SerializerMethodField()

    def get_total_hours_spent(self, obj):
        # Use the reverse generic relation. Django automatically provides this.
        # The related_name on the GFK is 'issue_key'.
        timers = obj.issue_key.exclude(finish_time__isnull=True)
        total_millis = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_millis / (1000 * 60 * 60), 2)  # Convert ms to hours

    def get_has_remnant_plate(self, obj):
        return len(obj.plate_usage_records.all()) > 0

    class Meta:
        model = CncTask
        fields = [
            'key', 'machine_fk', 'machine_name', 'name', 'nesting_id', 'material', 'dimensions', 'quantity',
            'thickness_mm', 'completion_date', 'completed_by', 'completed_by_username', 'estimated_hours',
            'total_hours_spent', 'parts_count', 'in_plan', 'plan_order',
            'planning_request_item', 'plate_item_code', 'plate_item_name',
            'plate_item_is_delivered', 'plate_item_is_consumed', 'has_remnant_plate'
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

    # Remnant plate usage records (read-only for GET requests)
    plate_usage_records = RemnantPlateUsageSerializer(many=True, read_only=True)

    # For setting a single remnant plate (backward compatibility and convenience)
    # This will create/update a RemnantPlateUsage record with quantity_used=1
    selected_plate_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    quantity_used = serializers.IntegerField(write_only=True, required=False, default=1)

    # Alternative plate source: a planning request item (plate stock line, code 0100/0101).
    # Same multipart semantics as selected_plate_id: '' clears, absent leaves untouched.
    planning_request_item_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    # Marks the linked planning item's physical stock as used up (or reverts it).
    # Only applied when the key is present in the request — multipart POSTs inject
    # False for absent BooleanFields, so presence is checked via initial_data.
    mark_item_consumed = serializers.BooleanField(write_only=True, required=False)
    plate_item = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CncTask
        fields = [
            'key', 'name', 'nesting_id', 'material', 'dimensions',
            'thickness_mm', 'parts', 'files', 'machine_fk', 'machine_name',
            'estimated_hours', 'quantity', 'plate_usage_records',
            'selected_plate_id', 'quantity_used',
            'planning_request_item_id', 'mark_item_consumed', 'plate_item'
        ]
        read_only_fields = ['key']
        extra_kwargs = {
            # No file field here anymore, it's handled manually
        }

    def get_plate_item(self, obj):
        from django.db.models import Sum, Value
        from django.db.models.functions import Coalesce

        pri = obj.planning_request_item
        if not pri:
            return None
        # Quantity-weighted usage: a cut with Adet=3 used the line 3 times.
        cuts_total = pri.cnc_tasks.aggregate(
            total=Sum(Coalesce('quantity', Value(1))))['total'] or 0
        return {
            'id': pri.id,
            'item_code': pri.item.code,
            'item_name': pri.item.name,
            'item_unit': pri.item.unit,
            'job_no': pri.job_no,
            'quantity': pri.quantity,
            'planning_request_number': pri.planning_request.request_number,
            'is_delivered': pri.is_delivered,
            'is_consumed': pri.is_consumed,
            'cnc_cuts_count': cuts_total,
        }

    def _get_planning_item(self, item_id, current_id=None):
        """Resolve and validate a plate planning-request item for use as a cut source."""
        from planning.models import PlanningRequestItem
        try:
            item = PlanningRequestItem.objects.select_related('item', 'planning_request').get(id=item_id)
        except PlanningRequestItem.DoesNotExist:
            raise serializers.ValidationError({"planning_request_item_id": "Planlama talebi kalemi bulunamadı."})
        code = item.item.code or ''
        if not code.startswith(PLATE_ITEM_CODE_PREFIXES):
            raise serializers.ValidationError({
                "planning_request_item_id": (
                    f"Seçilen kalem bir plaka kalemi değil (kod: {code}). "
                    f"Plaka kalem kodları {' veya '.join(PLATE_ITEM_CODE_PREFIXES)} ile başlar."
                )
            })
        if item.is_consumed and item.id != current_id:
            raise serializers.ValidationError({
                "planning_request_item_id": "Bu kalem 'kullanıldı' olarak işaretlenmiş; yeni kesim için seçilemez."
            })
        return item

    def _apply_consumed_flag(self, item, flag, user):
        """Transition-only consumed update; no-op when the item is already in the target state."""
        if flag and not item.is_consumed:
            item.is_consumed = True
            item.consumed_at = timezone.now()
            item.consumed_by = user if (user and user.is_authenticated) else None
        elif not flag and item.is_consumed:
            item.is_consumed = False
            item.consumed_at = None
            item.consumed_by = None
        else:
            return
        item.save(update_fields=['is_consumed', 'consumed_at', 'consumed_by'])

    def _validate_remnant_for_create(self, selected_plate_id, quantity_used):
        try:
            remnant_plate = RemnantPlate.objects.get(id=selected_plate_id)
        except RemnantPlate.DoesNotExist:
            raise serializers.ValidationError({"selected_plate_id": "Remnant plate not found."})
        available = remnant_plate.available_quantity()
        if quantity_used > available:
            raise serializers.ValidationError({
                "quantity_used": f"Cannot use {quantity_used} plates. Only {available} available (Total: {remnant_plate.quantity}, Already used: {(remnant_plate.quantity or 0) - available})."
            })
        return remnant_plate

    def create(self, validated_data):
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        # Extract plate-source data
        selected_plate_id = validated_data.pop('selected_plate_id', None)
        quantity_used = validated_data.pop('quantity_used', 1)
        planning_item_id = validated_data.pop('planning_request_item_id', None)
        mark_consumed_present = 'mark_item_consumed' in self.initial_data
        mark_item_consumed = validated_data.pop('mark_item_consumed', False)

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

        # Every cut consumes exactly one plate source: a remnant plate or a plate stock line.
        if selected_plate_id and planning_item_id:
            raise serializers.ValidationError({
                "planning_request_item_id": "Bir kesim için ya fire plaka ya da plaka kalemi seçilebilir, ikisi birden değil."
            })
        if not selected_plate_id and not planning_item_id:
            raise serializers.ValidationError({
                "planning_request_item_id": "Kesim oluşturmak için fire plaka veya plaka kalemi seçilmelidir."
            })
        if mark_consumed_present and mark_item_consumed and not planning_item_id:
            raise serializers.ValidationError({
                "mark_item_consumed": "'Kullanıldı' işareti yalnızca plaka kalemi seçiliyken uygulanabilir."
            })

        # Resolve and validate the chosen source BEFORE creating anything,
        # so a validation error can't leave an orphan task behind.
        remnant_plate = None
        planning_item = None
        if selected_plate_id:
            remnant_plate = self._validate_remnant_for_create(selected_plate_id, quantity_used)
        if planning_item_id:
            planning_item = self._get_planning_item(planning_item_id)

        # Derive plate details from the chosen source when not provided explicitly.
        if planning_item is not None:
            validated_data['planning_request_item'] = planning_item
            if not validated_data.get('material'):
                validated_data['material'] = planning_item.item.name
            if validated_data.get('thickness_mm') is None:
                validated_data['thickness_mm'] = parse_thickness_from_item_name(planning_item.item.name)
            if validated_data.get('quantity') is None:
                validated_data['quantity'] = 1
        if remnant_plate is not None:
            if not validated_data.get('material') and remnant_plate.material:
                validated_data['material'] = remnant_plate.material
            if validated_data.get('thickness_mm') is None and remnant_plate.thickness_mm is not None:
                validated_data['thickness_mm'] = remnant_plate.thickness_mm
            if not validated_data.get('dimensions') and remnant_plate.dimensions:
                validated_data['dimensions'] = remnant_plate.dimensions
            if validated_data.get('quantity') is None:
                validated_data['quantity'] = quantity_used or 1

        with transaction.atomic():
            # Generate a unique key if one isn't provided, similar to machining tasks.
            if 'key' not in validated_data or not validated_data['key']:
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

            if remnant_plate is not None:
                RemnantPlateUsage.objects.create(
                    cnc_task=cnc_task,
                    remnant_plate=remnant_plate,
                    quantity_used=quantity_used
                )

            if planning_item is not None and mark_consumed_present:
                self._apply_consumed_flag(planning_item, mark_item_consumed, user)

        return cnc_task

    def update(self, instance, validated_data):
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        # Extract plate-source data
        selected_plate_id = validated_data.pop('selected_plate_id', None)
        quantity_used = validated_data.pop('quantity_used', 1)
        planning_item_id = validated_data.pop('planning_request_item_id', None)
        mark_consumed_present = 'mark_item_consumed' in self.initial_data
        mark_item_consumed = validated_data.pop('mark_item_consumed', False)

        plate_present = 'selected_plate_id' in self.initial_data
        item_present = 'planning_request_item_id' in self.initial_data

        if selected_plate_id and planning_item_id:
            raise serializers.ValidationError({
                "planning_request_item_id": "Bir kesim için ya fire plaka ya da plaka kalemi seçilebilir, ikisi birden değil."
            })

        # Resolve and validate targets BEFORE mutating anything.
        new_remnant = None
        if selected_plate_id:
            try:
                new_remnant = RemnantPlate.objects.get(id=selected_plate_id)
            except RemnantPlate.DoesNotExist:
                raise serializers.ValidationError({"selected_plate_id": "Remnant plate not found."})

            # Get current usage by this task (will be deleted and re-created)
            current_usage = instance.plate_usage_records.filter(remnant_plate=new_remnant).first()
            current_quantity_used = current_usage.quantity_used if current_usage else 0

            # Calculate available quantity (add back what this task is currently using)
            available = new_remnant.available_quantity() + current_quantity_used
            if quantity_used > available:
                raise serializers.ValidationError({
                    "quantity_used": f"Cannot use {quantity_used} plates. Only {available} available (Total: {new_remnant.quantity}, Already used by others: {(new_remnant.quantity or 0) - available})."
                })

        new_item = None
        if planning_item_id:
            new_item = self._get_planning_item(planning_item_id, current_id=instance.planning_request_item_id)

        # The planning item the task will be linked to after this update.
        if new_item is not None:
            final_item = new_item
        elif item_present or new_remnant is not None:
            final_item = None  # explicitly cleared, or replaced by a remnant plate
        else:
            final_item = instance.planning_request_item

        if mark_consumed_present and mark_item_consumed and final_item is None:
            raise serializers.ValidationError({
                "mark_item_consumed": "'Kullanıldı' işareti yalnızca plaka kalemi bağlıyken uygulanabilir."
            })

        with transaction.atomic():
            # Update regular fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)

            # Plate-source updates. Setting one source always clears the other,
            # including when the other key is absent from the request.
            if new_item is not None:
                instance.planning_request_item = new_item
                instance.plate_usage_records.all().delete()
                if 'material' not in self.initial_data:
                    instance.material = new_item.item.name
                if 'thickness_mm' not in self.initial_data:
                    instance.thickness_mm = parse_thickness_from_item_name(new_item.item.name)
            elif item_present:
                instance.planning_request_item = None

            if new_remnant is not None:
                instance.planning_request_item = None
                instance.plate_usage_records.all().delete()
                RemnantPlateUsage.objects.create(
                    cnc_task=instance,
                    remnant_plate=new_remnant,
                    quantity_used=quantity_used
                )
                if 'material' not in self.initial_data and new_remnant.material:
                    instance.material = new_remnant.material
                if 'thickness_mm' not in self.initial_data and new_remnant.thickness_mm is not None:
                    instance.thickness_mm = new_remnant.thickness_mm
                if 'dimensions' not in self.initial_data and new_remnant.dimensions:
                    instance.dimensions = new_remnant.dimensions
            elif plate_present and selected_plate_id is None:
                instance.plate_usage_records.all().delete()

            instance.save()

            if mark_consumed_present and final_item is not None:
                self._apply_consumed_flag(final_item, mark_item_consumed, user)

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