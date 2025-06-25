from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile

class UserListSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    is_admin = serializers.BooleanField(source='profile.is_admin')
    must_reset_password = serializers.BooleanField(source='profile.must_reset_password')

    class Meta:
        model = User
        fields = ['username', 'team', 'is_admin', 'must_reset_password']


class UserCreateSerializer(serializers.ModelSerializer):
    team = serializers.CharField(write_only=True)
    is_admin = serializers.BooleanField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'password', 'team']

    def create(self, validated_data):
        team = validated_data.pop('team')
        password = validated_data.pop('password')

        user = User.objects.create(username=validated_data['username'])
        user.set_password(password)
        user.save()

        UserProfile.objects.create(
            user=user,
            team=team,
            must_reset_password=True
        )

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