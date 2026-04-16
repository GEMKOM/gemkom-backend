from rest_framework import serializers
from django.db import transaction
import time

from .models import LinearCuttingSession, LinearCuttingPart, LinearCuttingTask
from tasks.serializers import BaseTimerSerializer


# ─────────────────────────────────────────────────────────────────────────────
# Part serializers
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingPartSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source='item.code', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True, allow_null=True)
    item_unit = serializers.CharField(source='item.unit', read_only=True, allow_null=True)

    class Meta:
        model = LinearCuttingPart
        fields = [
            'id', 'session', 'item', 'item_code', 'item_name', 'item_unit',
            'stock_length_mm',
            'label', 'job_no',
            'nominal_length_mm', 'quantity',
            'angle_left_deg', 'angle_right_deg', 'profile_height_mm',
            'order',
        ]
        read_only_fields = ['id']


class LinearCuttingPartWriteSerializer(serializers.ModelSerializer):
    """Used for nested creation inside a session."""
    class Meta:
        model = LinearCuttingPart
        fields = [
            'item', 'stock_length_mm',
            'label', 'job_no',
            'nominal_length_mm', 'quantity',
            'angle_left_deg', 'angle_right_deg', 'profile_height_mm',
            'order',
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Session serializers
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingSessionListSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    planning_request_number = serializers.CharField(source='planning_request.request_number', read_only=True, allow_null=True)
    parts_count = serializers.SerializerMethodField()
    # Per-item-group summary derived from optimization_result
    optimization_summary = serializers.SerializerMethodField()

    def get_parts_count(self, obj):
        return obj.parts.count()

    def get_optimization_summary(self, obj):
        """Returns a compact summary per item group from optimization_result."""
        if not obj.optimization_result:
            return []
        groups = obj.optimization_result.get('groups', [])
        return [
            {
                'item_id': g.get('item_id'),
                'item_name': g.get('item_name'),
                'item_code': g.get('item_code'),
                'stock_length_mm': g.get('stock_length_mm'),
                'bars_needed': g.get('bars_needed'),
                'total_waste_mm': g.get('total_waste_mm'),
                'efficiency_pct': g.get('efficiency_pct'),
            }
            for g in groups
        ]

    class Meta:
        model = LinearCuttingSession
        fields = [
            'key', 'title', 'stock_length_mm', 'kerf_mm',
            'tasks_created', 'planning_request_created',
            'planning_request', 'planning_request_number',
            'created_by', 'created_by_username', 'created_at',
            'parts_count', 'optimization_summary',
        ]


class LinearCuttingSessionDetailSerializer(serializers.ModelSerializer):
    parts = LinearCuttingPartSerializer(many=True, read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    planning_request_number = serializers.CharField(source='planning_request.request_number', read_only=True, allow_null=True)

    # Write-only: list of parts to create together with the session
    parts_data = LinearCuttingPartWriteSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = LinearCuttingSession
        fields = [
            'key', 'title', 'stock_length_mm', 'kerf_mm', 'notes',
            'tasks_created', 'planning_request_created',
            'planning_request', 'planning_request_number',
            'optimization_result',
            'created_by', 'created_by_username', 'created_at',
            'parts', 'parts_data',
        ]
        read_only_fields = [
            'key', 'optimization_result',
            'tasks_created', 'planning_request_created',
            'planning_request', 'created_by', 'created_at',
        ]

    def create(self, validated_data):
        parts_data = validated_data.pop('parts_data', [])
        user = self.context['request'].user
        validated_data['created_by'] = user
        validated_data['created_at'] = int(time.time() * 1000)

        with transaction.atomic():
            session = LinearCuttingSession.objects.create(**validated_data)
            for i, part in enumerate(parts_data):
                if 'order' not in part:
                    part['order'] = i
                LinearCuttingPart.objects.create(session=session, **part)

        return session

    def update(self, instance, validated_data):
        # Parts are managed separately via their own endpoint; ignore parts_data on PATCH
        validated_data.pop('parts_data', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


# ─────────────────────────────────────────────────────────────────────────────
# Task serializers
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingTaskListSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    completed_by_username = serializers.CharField(source='completed_by.username', read_only=True, allow_null=True)
    session_title = serializers.CharField(source='session.title', read_only=True)
    item_code = serializers.CharField(source='item.code', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True, allow_null=True)
    total_hours_spent = serializers.SerializerMethodField()

    def get_total_hours_spent(self, obj):
        timers = obj.issue_key.exclude(finish_time__isnull=True)
        total_ms = sum((t.finish_time - t.start_time) for t in timers)
        return round(total_ms / (1000 * 60 * 60), 2)

    class Meta:
        model = LinearCuttingTask
        fields = [
            'key', 'session', 'session_title', 'bar_index', 'name',
            'stock_length_mm', 'material', 'waste_mm',
            'item', 'item_code', 'item_name',
            'machine_fk', 'machine_name',
            'completion_date', 'completed_by', 'completed_by_username',
            'estimated_hours', 'total_hours_spent',
            'in_plan', 'plan_order',
        ]


class LinearCuttingTaskDetailSerializer(serializers.ModelSerializer):
    machine_name = serializers.CharField(source='machine_fk.name', read_only=True, allow_null=True)
    item_code = serializers.CharField(source='item.code', read_only=True, allow_null=True)
    item_name = serializers.CharField(source='item.name', read_only=True, allow_null=True)

    class Meta:
        model = LinearCuttingTask
        fields = [
            'key', 'session', 'bar_index', 'name', 'description',
            'stock_length_mm', 'material', 'layout_json', 'waste_mm',
            'item', 'item_code', 'item_name',
            'machine_fk', 'machine_name',
            'completion_date', 'completed_by', 'estimated_hours',
            'in_plan', 'plan_order', 'planned_start_ms', 'planned_end_ms',
        ]
        read_only_fields = ['key', 'session', 'bar_index', 'layout_json']


# ─────────────────────────────────────────────────────────────────────────────
# Timer serializer (extends BaseTimerSerializer with task-specific read fields)
# ─────────────────────────────────────────────────────────────────────────────

class LinearCuttingTimerSerializer(BaseTimerSerializer):
    session_key = serializers.CharField(source='issue_key.session.key', read_only=True, allow_null=True)
    bar_index = serializers.IntegerField(source='issue_key.bar_index', read_only=True, allow_null=True)
    material = serializers.CharField(source='issue_key.material', read_only=True, allow_null=True)

    class Meta(BaseTimerSerializer.Meta):
        fields = BaseTimerSerializer.Meta.fields + ['session_key', 'bar_index', 'material']
