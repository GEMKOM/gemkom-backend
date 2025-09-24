from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile

class PublicUserSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    team_label = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'team', 'team_label']

    def get_team_label(self, obj):
        if hasattr(obj, 'profile') and obj.profile.team:
            return obj.profile.get_team_display()
        return None

class UserPasswordResetSerializer(serializers.ModelSerializer):
    reset_password_request = serializers.BooleanField(source='profile.reset_password_request')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')
    team = serializers.CharField(source='profile.team')

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_superuser',
            'team', 'reset_password_request', 'must_reset_password'
        ]
    
class UserListSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    occupation = serializers.CharField(source='profile.occupation')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')
    team_label = serializers.SerializerMethodField()
    occupation_label = serializers.SerializerMethodField()

    work_location = serializers.CharField(source='profile.work_location')
    work_location_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'first_name', 'last_name', 'email', 'is_superuser',
            'team', 'team_label', 'occupation', 'occupation_label', 'work_location', 'work_location_label', 'must_reset_password'
        ]

    def get_work_location_label(self, obj):
        if hasattr(obj, 'profile') and obj.profile.work_location:
            return obj.profile.get_work_location_display()
        return None

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
    work_location = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'team', 'work_location']

    def create(self, validated_data):
        team = validated_data.pop('team', None)
        work_location = validated_data.pop('work_location', None)

        # Create user with remaining data (first_name, last_name, etc.)
        user = User.objects.create(
            username=validated_data.get('username'),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            email=validated_data.get('email', '')
        )
        user.set_password("gemkom2025.")  # You can change this later
        user.save()

        # Create or update profile
        UserProfile.objects.update_or_create(user=user, defaults={
            'team': team,
            'work_location': work_location,
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

class CurrentUserUpdateSerializer(serializers.ModelSerializer):
    jira_api_token = serializers.CharField(source="profile.jira_api_token", allow_blank=True, required=False)

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'jira_api_token']

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
    

class AdminUserUpdateSerializer(serializers.ModelSerializer):
    jira_api_token = serializers.CharField(source="profile.jira_api_token", allow_blank=True, required=False)
    team = serializers.CharField(source='profile.team')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')
    occupation = serializers.CharField(source='profile.occupation')
    work_location = serializers.CharField(source='profile.work_location')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'jira_api_token', 'team', 'must_reset_password', 'occupation', 'work_location']

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
