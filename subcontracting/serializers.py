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

        # Paint tier weight mirrors other tiers — exclude it from the cap check
        from subcontracting.services.painting import PAINT_TIER_NAME
        name = data.get('name', getattr(self.instance, 'name', ''))
        if name == PAINT_TIER_NAME:
            return data

        # Sum of all other non-paint tiers for this job order
        qs = SubcontractingPriceTier.objects.filter(
            job_order=job_order
        ).exclude(name=PAINT_TIER_NAME)
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
    current_progress = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    current_cost_eur = serializers.SerializerMethodField()
    unbilled_cost_eur = serializers.SerializerMethodField()
    projected_cost = serializers.SerializerMethodField()

    # Convenient read-only summaries
    subcontractor_name = serializers.CharField(source='subcontractor.name', read_only=True)
    price_tier_name = serializers.CharField(source='price_tier.name', read_only=True)
    price_per_kg = serializers.DecimalField(
        source='price_tier.price_per_kg', max_digits=12, decimal_places=4, read_only=True
    )
    job_no = serializers.CharField(source='department_task.job_order_id', read_only=True)

    def _billed_date(self, obj):
        """
        Date to use for FX on the billed portion: approved_at of the most
        recent approved statement line, falling back to assignment.updated_at
        then created_at.
        """
        from datetime import date as date_type
        last_line = (
            obj.statement_lines
            .filter(statement__approved_at__isnull=False)
            .order_by('-statement__approved_at')
            .select_related('statement')
            .first()
        )
        if last_line and last_line.statement.approved_at:
            return last_line.statement.approved_at.date()
        return obj.updated_at.date() if obj.updated_at else obj.created_at.date()

    def _unbilled_date(self, obj):
        """Date to use for FX on the unbilled portion: assignment.updated_at or created_at."""
        return obj.updated_at.date() if obj.updated_at else obj.created_at.date()

    def get_current_cost_eur(self, obj):
        """Billed cost in EUR using approved statement date for FX."""
        from projects.services.costing import convert_to_eur
        raw = obj.current_cost
        if not raw:
            return '0.00'
        return str(convert_to_eur(raw, obj.cost_currency, self._billed_date(obj)))

    def get_unbilled_cost_eur(self, obj):
        """Unbilled cost in EUR using assignment updated_at for FX."""
        from projects.services.costing import convert_to_eur
        raw = obj.unbilled_cost
        if not raw:
            return '0.00'
        return str(convert_to_eur(raw, obj.price_tier.currency, self._unbilled_date(obj)))

    def get_projected_cost(self, obj):
        """Full contract value at 100% completion in EUR using the assignment's created_at date for FX."""
        from projects.services.costing import convert_to_eur
        raw = (obj.allocated_weight_kg * obj.price_tier.price_per_kg).quantize(Decimal('0.01'))
        return str(convert_to_eur(raw, obj.price_tier.currency, obj.created_at.date()))

    class Meta:
        model = SubcontractingAssignment
        fields = [
            'id', 'department_task', 'subcontractor', 'subcontractor_name',
            'price_tier', 'price_tier_name', 'price_per_kg', 'job_no',
            'allocated_weight_kg',
            'current_cost', 'cost_currency', 'current_cost_eur',
            'last_billed_progress', 'current_progress',
            'unbilled_progress', 'unbilled_cost_eur',
            'projected_cost',
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

        # Painting tasks are direct subtasks auto-assigned by the system — skip parent check.
        # All other assignments must be subtasks under a 'Kaynaklı İmalat' (welding) parent.
        if dept_task.task_type != 'painting':
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


# ---------------------------------------------------------------------------
# Subcontractor Overview
# ---------------------------------------------------------------------------

def _assignment_costs(assignment) -> dict:
    """
    Compute the four cost breakdown values for a single assignment.

    - total_billed_cost      : cost for last_billed_progress (already invoiced & approved)
    - next_bill_cost         : cost for unbilled progress done so far (current - last_billed)
    - unbilled_remaining_cost: cost for work not yet done (100% - current_progress)
    - total_cost             : full contract value at 100%
    """
    a = assignment
    ppkg = a.price_tier.price_per_kg
    wkg  = a.allocated_weight_kg

    total_cost               = (wkg * ppkg).quantize(Decimal('0.01'))
    total_billed_cost        = (wkg * (a.last_billed_progress / Decimal('100')) * ppkg).quantize(Decimal('0.01'))
    next_bill_cost           = a.unbilled_cost
    remaining_progress       = max(Decimal('0'), Decimal('100') - a.current_progress)
    unbilled_remaining_cost  = (wkg * (remaining_progress / Decimal('100')) * ppkg).quantize(Decimal('0.01'))

    return {
        'allocated_weight_kg':     wkg,
        'total_billed_cost':       total_billed_cost,
        'next_bill_cost':          next_bill_cost,
        'unbilled_remaining_cost': unbilled_remaining_cost,
        'total_cost':              total_cost,
    }


class SubcontractorOverviewJobOrderSerializer(serializers.Serializer):
    """Aggregated cost breakdown for one job order under a subcontractor."""
    job_no                   = serializers.CharField()
    job_title                = serializers.CharField()
    job_status               = serializers.CharField()
    customer_name            = serializers.CharField()
    currency                 = serializers.CharField()
    allocated_weight_kg      = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_billed_cost        = serializers.DecimalField(max_digits=16, decimal_places=2)
    next_bill_cost           = serializers.DecimalField(max_digits=16, decimal_places=2)
    unbilled_remaining_cost  = serializers.DecimalField(max_digits=16, decimal_places=2)
    total_cost               = serializers.DecimalField(max_digits=16, decimal_places=2)


class SubcontractorOverviewSerializer(serializers.ModelSerializer):
    """Subcontractor with aggregated cost breakdown across all job orders."""
    job_orders              = serializers.SerializerMethodField()
    allocated_weight_kg     = serializers.SerializerMethodField()
    total_billed_cost       = serializers.SerializerMethodField()
    next_bill_cost          = serializers.SerializerMethodField()
    unbilled_remaining_cost = serializers.SerializerMethodField()
    total_cost              = serializers.SerializerMethodField()

    class Meta:
        model = Subcontractor
        fields = [
            'id', 'name', 'short_name', 'contact_person', 'phone', 'email',
            'default_currency', 'is_active',
            'allocated_weight_kg',
            'total_billed_cost', 'next_bill_cost',
            'unbilled_remaining_cost', 'total_cost',
            'job_orders',
        ]

    def _costs_by_job(self, obj):
        """Build and cache per-job aggregated cost dicts."""
        if not hasattr(obj, '_overview_costs'):
            groups: dict[str, list] = {}
            for a in obj.assignments.all():
                groups.setdefault(a.department_task.job_order_id, []).append(a)

            jobs = []
            for job_no, job_assignments in sorted(groups.items()):
                job_order = job_assignments[0].department_task.job_order
                currency  = job_assignments[0].cost_currency

                totals = {
                    'allocated_weight_kg':     Decimal('0.00'),
                    'total_billed_cost':       Decimal('0.00'),
                    'next_bill_cost':          Decimal('0.00'),
                    'unbilled_remaining_cost': Decimal('0.00'),
                    'total_cost':              Decimal('0.00'),
                }
                for a in job_assignments:
                    c = _assignment_costs(a)
                    for k in totals:
                        totals[k] += c[k]

                jobs.append({
                    'job_no':        job_no,
                    'job_title':     job_order.title,
                    'job_status':    job_order.status,
                    'customer_name': job_order.customer.name if job_order.customer_id else '',
                    'currency':      currency,
                    **totals,
                })

            obj._overview_costs = jobs
        return obj._overview_costs

    def get_job_orders(self, obj):
        return SubcontractorOverviewJobOrderSerializer(
            self._costs_by_job(obj), many=True
        ).data

    def _sum_field(self, obj, field):
        return str(sum(
            (j[field] for j in self._costs_by_job(obj)), Decimal('0.00')
        ))

    def get_allocated_weight_kg(self, obj):     return self._sum_field(obj, 'allocated_weight_kg')
    def get_total_billed_cost(self, obj):       return self._sum_field(obj, 'total_billed_cost')
    def get_next_bill_cost(self, obj):          return self._sum_field(obj, 'next_bill_cost')
    def get_unbilled_remaining_cost(self, obj): return self._sum_field(obj, 'unbilled_remaining_cost')
    def get_total_cost(self, obj):              return self._sum_field(obj, 'total_cost')
