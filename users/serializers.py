from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile, WageRate


class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name']

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
            'team', 'team_label', 'occupation', 'occupation_label', 'work_location', 'work_location_label', 'must_reset_password',
            'is_active'
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

class UserMiniSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source="profile.team", read_only=True)
    team_label = serializers.CharField(source="profile.get_team_display", read_only=True)
    occupation = serializers.CharField(source="profile.occupation", read_only=True)
    occupation_label = serializers.CharField(source="profile.get_occupation_display", read_only=True)
    work_location = serializers.CharField(source="profile.work_location", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name",
            "team", "team_label", "occupation", "occupation_label", "work_location",
        ]

class UserWageOverviewSerializer(serializers.ModelSerializer):
    """
    Represents one user + their *current* wage (if any).
    The current wage fields are annotated in the queryset.
    """
    user_info = UserMiniSerializer(source="*", read_only=True)
    has_wage = serializers.BooleanField(read_only=True)
    current_wage = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "user_info", "has_wage", "current_wage"]

    def get_current_wage(self, obj):
        if getattr(obj, "current_wage_id", None) is None:
            return None
        return {
            "id": obj.current_wage_id,
            "effective_from": obj.current_effective_from,
            "base_monthly": obj.current_base_monthly,
            "after_hours_multiplier": obj.current_after_hours_multiplier,
            "sunday_multiplier": obj.current_sunday_multiplier,
        }

class WageRateSerializer(serializers.ModelSerializer):
    from django.contrib.auth.models import User as DjangoUser
    user = serializers.PrimaryKeyRelatedField(queryset=DjangoUser.objects.all())
    user_info = UserMiniSerializer(source="user", read_only=True)

    class Meta:
        model = WageRate
        fields = [
            "id", "user", "user_info",
            "effective_from", "currency",
            "base_monthly", "after_hours_multiplier", "sunday_multiplier",
            "note", "created_at", "created_by", "updated_at", "updated_by",
        ]
        read_only_fields = ["created_at", "created_by", "updated_at", "updated_by"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        validated_data["updated_by"] = self.context["request"].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)
    
class WageRateSlimSerializer(WageRateSerializer):
    class Meta(WageRateSerializer.Meta):
        # reuse existing fields, just drop user-related ones
        fields = [f for f in WageRateSerializer.Meta.fields if f not in ("user_info")]