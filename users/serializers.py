from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile

class UserListSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    occupation = serializers.CharField(source='profile.occupation')
    is_admin = serializers.BooleanField(source='profile.is_admin')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')
    is_lead = serializers.BooleanField(source='profile.is_lead')
    team_label = serializers.SerializerMethodField()
    occupation_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_superuser', 'team', 'team_label', 'is_admin', 'is_lead', 'must_reset_password', 'occupation', 'occupation_label']

    def get_team_label(self, obj):
        if hasattr(obj, 'profile') and obj.profile.team:
            return obj.profile.get_team_display()
        return None
    
    def get_occupation_label(self, obj):
        if hasattr(obj, 'profile') and obj.profile.occupation:
            return obj.profile.get_occupation_display()
        return None


class UserCreateSerializer(serializers.ModelSerializer):
    team = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'team']

    def create(self, validated_data):
        team = validated_data.pop('team')
        user = User.objects.create(username=validated_data['username'])
        user.set_password("gemkom2025.")  # You may want to make this configurable later
        user.save()

        UserProfile.objects.update_or_create(user=user, defaults={
            'team': team,
            'must_reset_password': True
        })

        return user
    
class PasswordResetSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_new_password(self, value):
        # Add any custom password validation here
        return value

    def save(self, user):
        user.set_password(self.validated_data['new_password'])
        user.save()
        profile = user.profile
        profile.must_reset_password = False
        profile.save()

class UserUpdateSerializer(serializers.ModelSerializer):
    jira_api_token = serializers.CharField(source="profile.jira_api_token", allow_blank=True, required=False)
    team = serializers.CharField(source='profile.team')
    is_admin = serializers.BooleanField(source='profile.is_admin')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')
    occupation = serializers.CharField(source='profile.occupation')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'jira_api_token', 'team', 'is_admin', 'must_reset_password', 'occupation']

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        profile = instance.profile
        for attr, value in profile_data.items():
            setattr(profile, attr, value)
        profile.save()

        return instance
