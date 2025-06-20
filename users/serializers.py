from django.contrib.auth.models import User
from rest_framework import serializers
from .models import UserProfile

class UserListSerializer(serializers.ModelSerializer):
    team = serializers.CharField(source='profile.team')
    is_admin = serializers.BooleanField(source='profile.is_admin')

    class Meta:
        model = User
        fields = ['username', 'team', 'is_admin']
