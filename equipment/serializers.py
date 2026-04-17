from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from .models import EquipmentItem, EquipmentCheckout

User = get_user_model()


# ─── Minimal nested serializers ───────────────────────────────────────────────

class EquipmentItemMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentItem
        fields = ['id', 'code', 'name']


class UserMinimalSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


# ─── EquipmentItem serializers ─────────────────────────────────────────────────

class EquipmentItemListSerializer(serializers.ModelSerializer):
    available_quantity = serializers.IntegerField(read_only=True)
    checked_out_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = EquipmentItem
        fields = [
            'id', 'code', 'name', 'asset_type', 'category',
            'quantity', 'available_quantity', 'checked_out_quantity',
            'location', 'is_active',
        ]


class EquipmentItemDetailSerializer(serializers.ModelSerializer):
    available_quantity = serializers.IntegerField(read_only=True)
    checked_out_quantity = serializers.IntegerField(read_only=True)
    asset_type_display = serializers.CharField(source='get_asset_type_display', read_only=True)
    recent_checkouts = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentItem
        fields = [
            'id', 'code', 'name', 'description', 'asset_type', 'asset_type_display',
            'category', 'quantity', 'available_quantity', 'checked_out_quantity',
            'location', 'is_active', 'properties',
            'created_at', 'updated_at', 'recent_checkouts',
        ]

    def get_recent_checkouts(self, obj):
        qs = obj.checkouts.select_related(
            'checked_out_by', 'checked_in_by'
        ).order_by('-checked_out_at')[:10]
        return EquipmentCheckoutListSerializer(qs, many=True).data


class EquipmentItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentItem
        fields = [
            'code', 'name', 'description', 'asset_type', 'category',
            'quantity', 'location', 'is_active', 'properties',
        ]


# ─── EquipmentCheckout serializers ────────────────────────────────────────────

class EquipmentCheckoutListSerializer(serializers.ModelSerializer):
    item = EquipmentItemMinimalSerializer(read_only=True)
    checked_out_by = UserMinimalSerializer(read_only=True)
    checked_in_by = UserMinimalSerializer(read_only=True)
    is_returned = serializers.BooleanField(read_only=True)
    job_order_no = serializers.CharField(source='job_order_id', read_only=True, allow_null=True)

    class Meta:
        model = EquipmentCheckout
        fields = [
            'id', 'item', 'quantity',
            'checked_out_by', 'checked_out_at',
            'job_order_no', 'purpose',
            'is_returned', 'checked_in_at', 'checked_in_by',
        ]


class EquipmentCheckoutCreateSerializer(serializers.ModelSerializer):
    item = serializers.PrimaryKeyRelatedField(
        queryset=EquipmentItem.objects.filter(is_active=True)
    )
    checked_out_by = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False
    )
    job_order = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = EquipmentCheckout
        fields = ['item', 'quantity', 'checked_out_by', 'job_order', 'purpose', 'notes']

    def validate_job_order(self, value):
        if not value:
            return None
        from projects.models import JobOrder
        try:
            return JobOrder.objects.get(job_no=value)
        except JobOrder.DoesNotExist:
            raise serializers.ValidationError(f"JobOrder '{value}' not found.")

    def validate(self, attrs):
        item = attrs['item']
        quantity = attrs.get('quantity', 1)
        item.refresh_from_db()
        if item.available_quantity < quantity:
            raise serializers.ValidationError(
                f"Requested {quantity} but only {item.available_quantity} available for '{item.code}'."
            )
        return attrs

    def create(self, validated_data):
        if 'checked_out_by' not in validated_data:
            validated_data['checked_out_by'] = self.context['request'].user
        return super().create(validated_data)


class EquipmentCheckoutDetailSerializer(serializers.ModelSerializer):
    item = EquipmentItemMinimalSerializer(read_only=True)
    checked_out_by = UserMinimalSerializer(read_only=True)
    checked_in_by = UserMinimalSerializer(read_only=True)
    is_returned = serializers.BooleanField(read_only=True)
    job_order_no = serializers.CharField(source='job_order_id', read_only=True, allow_null=True)

    class Meta:
        model = EquipmentCheckout
        fields = [
            'id', 'item', 'quantity',
            'checked_out_by', 'checked_out_at',
            'job_order_no', 'purpose',
            'checked_in_at', 'checked_in_by', 'is_returned',
            'notes', 'created_at', 'updated_at',
        ]
