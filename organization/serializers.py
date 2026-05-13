from __future__ import annotations

from rest_framework import serializers
from django.contrib.auth.models import User

from .models import Position


class MiniUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'is_active']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class PositionSerializer(serializers.ModelSerializer):
    parent_title = serializers.CharField(source='parent.title', read_only=True)
    holder_count = serializers.SerializerMethodField()
    permission_count = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'id', 'title', 'level',
            'parent', 'parent_title',
            'department_code',
            'is_active', 'holder_count', 'permission_count',
        ]

    def get_holder_count(self, obj):
        return obj.holders.filter(user__is_active=True).count()

    def get_permission_count(self, obj):
        return obj.permissions.count()


class PositionDetailSerializer(PositionSerializer):
    codenames = serializers.SerializerMethodField()

    class Meta(PositionSerializer.Meta):
        fields = PositionSerializer.Meta.fields + ['codenames']

    def get_codenames(self, obj):
        return list(obj.permissions.values_list('codename', flat=True))


class PositionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ['id', 'title', 'level', 'parent', 'department_code', 'is_active']


class PositionTreeSerializer(serializers.ModelSerializer):
    """Recursive serializer for the full position tree."""
    children = serializers.SerializerMethodField()
    holder_count = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = ['id', 'title', 'level', 'department_code', 'is_active', 'holder_count', 'children']

    def get_children(self, obj):
        qs = obj.direct_reports.filter(is_active=True).order_by('level', 'title')
        return PositionTreeSerializer(qs, many=True, context=self.context).data

    def get_holder_count(self, obj):
        return obj.holders.filter(user__is_active=True).count()


class PositionHolderSerializer(serializers.ModelSerializer):
    """Lists users holding a position."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'is_active']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username
