from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Team

User = get_user_model()


class TeamMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class TeamSerializer(serializers.ModelSerializer):
    foreman_name = serializers.SerializerMethodField()
    members_detail = TeamMemberSerializer(source='members', many=True, read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            'id', 'name', 'foreman', 'foreman_name',
            'members', 'members_detail', 'member_count',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_foreman_name(self, obj):
        if obj.foreman_id:
            return obj.foreman.get_full_name() or obj.foreman.username
        return None

    def get_member_count(self, obj):
        return obj.members.count()


class TeamListSerializer(serializers.ModelSerializer):
    foreman_name = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ['id', 'name', 'foreman', 'foreman_name', 'member_count', 'is_active']

    def get_foreman_name(self, obj):
        if obj.foreman_id:
            return obj.foreman.get_full_name() or obj.foreman.username
        return None

    def get_member_count(self, obj):
        return obj.members.count()
