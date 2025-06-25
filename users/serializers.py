from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile

class UserListSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    is_admin = serializers.BooleanField(source='profile.is_admin')

    class Meta:
        model = User
        fields = ['username', 'team', 'is_admin']


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