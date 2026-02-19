from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from .models import (
    Subcontractor,
    SubcontractingAssignment,
    SubcontractingPriceTier,
    SubcontractorStatement,
    SubcontractorStatementAdjustment,
    SubcontractorStatementLine,
)


# ---------------------------------------------------------------------------
# Subcontractor
# ---------------------------------------------------------------------------

class SubcontractorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subcontractor
        fields = [
            'id', 'name', 'short_name', 'contact_person', 'phone', 'email',
            'address', 'tax_id', 'tax_office', 'bank_info', 'agreement_details',
            'default_currency', 'is_active',
            'created_at', 'created_by', 'updated_at',
        ]
        read_only_fields = ['created_at', 'created_by', 'updated_at']

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# SubcontractingPriceTier
# ---------------------------------------------------------------------------

class SubcontractingPriceTierSerializer(serializers.ModelSerializer):
    remaining_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    used_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )

    class Meta:
        model = SubcontractingPriceTier
        fields = [
            'id', 'job_order', 'name', 'price_per_kg', 'currency',
            'allocated_weight_kg', 'used_weight_kg', 'remaining_weight_kg',
            'created_at', 'created_by', 'updated_at',
        ]
        read_only_fields = ['created_at', 'created_by', 'updated_at']

    def validate(self, data):
        job_order = data.get('job_order', getattr(self.instance, 'job_order', None))
        allocated = data.get('allocated_weight_kg', getattr(self.instance, 'allocated_weight_kg', Decimal('0')))

        if not job_order.total_weight_kg:
            raise serializers.ValidationError(
                "İş emrinde toplam ağırlık (total_weight_kg) girilmeden fiyat kademesi oluşturulamaz."
            )

        # Sum of all other tiers for this job order
        qs = SubcontractingPriceTier.objects.filter(job_order=job_order)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        existing_total = qs.aggregate(t=Sum('allocated_weight_kg'))['t'] or Decimal('0')

        if existing_total + allocated > job_order.total_weight_kg:
            raise serializers.ValidationError(
                f"Toplam kademe ağırlığı ({existing_total + allocated} kg), "
                f"iş emri toplam ağırlığını ({job_order.total_weight_kg} kg) aşıyor."
            )
        return data

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# SubcontractingAssignment
# ---------------------------------------------------------------------------

class SubcontractingAssignmentSerializer(serializers.ModelSerializer):
    unbilled_progress = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    unbilled_cost = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    current_progress = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)

    # Convenient read-only summaries
    subcontractor_name = serializers.CharField(source='subcontractor.name', read_only=True)
    price_tier_name = serializers.CharField(source='price_tier.name', read_only=True)
    price_per_kg = serializers.DecimalField(
        source='price_tier.price_per_kg', max_digits=12, decimal_places=4, read_only=True
    )
    job_no = serializers.CharField(source='department_task.job_order_id', read_only=True)

    class Meta:
        model = SubcontractingAssignment
        fields = [
            'id', 'department_task', 'subcontractor', 'subcontractor_name',
            'price_tier', 'price_tier_name', 'price_per_kg', 'job_no',
            'allocated_weight_kg',
            'current_cost', 'cost_currency',
            'last_billed_progress', 'current_progress',
            'unbilled_progress', 'unbilled_cost',
            'created_at', 'created_by', 'updated_at',
        ]
        read_only_fields = [
            'current_cost', 'cost_currency', 'last_billed_progress',
            'created_at', 'created_by', 'updated_at',
        ]

    def validate(self, data):
        dept_task = data.get('department_task', getattr(self.instance, 'department_task', None))
        price_tier = data.get('price_tier', getattr(self.instance, 'price_tier', None))
        allocated = data.get('allocated_weight_kg', getattr(self.instance, 'allocated_weight_kg', Decimal('0')))

        # Must be a subtask whose parent is titled "Kaynaklı İmalat"
        if dept_task.parent_id is None:
            raise serializers.ValidationError(
                "Taşeron ataması yalnızca alt görevlere yapılabilir, ana göreve yapılamaz."
            )
        parent = dept_task.parent
        if parent.task_type != 'welding':
            raise serializers.ValidationError(
                "Taşeron ataması yalnızca 'Kaynaklı İmalat' alt görevi altındaki görevlere yapılabilir."
            )

        # Price tier must belong to the same job order
        if price_tier.job_order_id != dept_task.job_order_id:
            raise serializers.ValidationError(
                "Fiyat kademesi, görevin iş emriyle aynı iş emrine ait olmalıdır."
            )

        # Check remaining weight with a lock to avoid race conditions
        with transaction.atomic():
            locked_tier = SubcontractingPriceTier.objects.select_for_update().get(pk=price_tier.pk)
            remaining = locked_tier.remaining_weight_kg
            if self.instance:
                # Add back the current instance's own allocation
                remaining += self.instance.allocated_weight_kg
            if allocated > remaining:
                raise serializers.ValidationError(
                    f"Atanan ağırlık ({allocated} kg), kademede kalan ağırlığı ({remaining} kg) aşıyor."
                )

        return data

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# SubcontractorStatementAdjustment
# ---------------------------------------------------------------------------

class SubcontractorStatementAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubcontractorStatementAdjustment
        fields = [
            'id', 'statement', 'adjustment_type', 'amount',
            'reason', 'description', 'job_order',
            'created_at', 'created_by',
        ]
        read_only_fields = ['created_at', 'created_by', 'statement']

    def validate_amount(self, value):
        adj_type = self.initial_data.get('adjustment_type') or (
            self.instance.adjustment_type if self.instance else None
        )
        if adj_type == 'deduction' and value > 0:
            return -abs(value)
        if adj_type == 'addition' and value < 0:
            return abs(value)
        return value

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


# ---------------------------------------------------------------------------
# SubcontractorStatementLine (read-only)
# ---------------------------------------------------------------------------

class SubcontractorStatementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubcontractorStatementLine
        fields = [
            'id', 'assignment', 'job_no', 'job_title',
            'subcontractor_name', 'price_tier_name',
            'allocated_weight_kg',
            'previous_progress', 'current_progress', 'delta_progress',
            'effective_weight_kg', 'price_per_kg', 'cost_amount',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# SubcontractorStatement
# ---------------------------------------------------------------------------

class SubcontractorStatementSerializer(serializers.ModelSerializer):
    line_items = SubcontractorStatementLineSerializer(many=True, read_only=True)
    adjustments = SubcontractorStatementAdjustmentSerializer(many=True, read_only=True)
    subcontractor_name = serializers.CharField(source='subcontractor.name', read_only=True)

    class Meta:
        model = SubcontractorStatement
        fields = [
            'id', 'subcontractor', 'subcontractor_name', 'year', 'month', 'status',
            'currency', 'work_total', 'adjustment_total', 'grand_total',
            'notes', 'line_items', 'adjustments',
            'created_at', 'created_by', 'updated_at', 'submitted_at', 'approved_at',
        ]
        read_only_fields = [
            'status', 'work_total', 'adjustment_total', 'grand_total',
            'created_at', 'created_by', 'updated_at', 'submitted_at', 'approved_at',
        ]

    def validate(self, data):
        # Ensure uniqueness (only relevant on create)
        if not self.instance:
            subcontractor = data.get('subcontractor')
            year = data.get('year')
            month = data.get('month')
            if SubcontractorStatement.objects.filter(
                subcontractor=subcontractor, year=year, month=month
            ).exists():
                raise serializers.ValidationError(
                    f"{subcontractor.name} için {year}/{month:02d} dönemi hakedişi zaten mevcut."
                )
        return data

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class SubcontractorStatementListSerializer(serializers.ModelSerializer):
    """Lightweight list serializer (no nested line items)."""
    subcontractor_name = serializers.CharField(source='subcontractor.name', read_only=True)

    class Meta:
        model = SubcontractorStatement
        fields = [
            'id', 'subcontractor', 'subcontractor_name', 'year', 'month', 'status',
            'currency', 'work_total', 'adjustment_total', 'grand_total',
            'created_at', 'submitted_at', 'approved_at',
        ]
