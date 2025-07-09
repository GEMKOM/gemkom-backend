import re
import unicodedata
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.generics import ListAPIView

from users.filters import UserFilter
from users.models import UserProfile
from users.permissions import IsAdmin
from .serializers import PasswordResetSerializer, UserCreateSerializer, UserListSerializer, UserUpdateSerializer
from rest_framework.permissions import IsAuthenticated, IsAdminUser

class UserListView(ListAPIView):
    queryset = User.objects.all().select_related('profile').order_by('username')
    serializer_class = UserListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = UserFilter

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        serializer = UserListSerializer(request.user)
        return Response(serializer.data)
    
    def put(self, request):
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User updated successfully."})
        return Response(serializer.errors, status=400)
    
class AdminCreateUserView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User created successfully"}, status=201)
        return Response(serializer.errors, status=400)
    

class ForcedPasswordResetView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.profile.must_reset_password:
            return Response({"detail": "Password reset not required."}, status=403)

        serializer = PasswordResetSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response({"detail": "Password updated successfully."}, status=200)
        return Response(serializer.errors, status=400)
    
class TeamChoicesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.TEAM_CHOICES
        ])
    
class AdminBulkCreateUsers(APIView):
    permission_classes = [IsAdminUser]  # Only superusers or staff with is_staff=True

    def post(self, request):
        names = request.data.get("names")
        team = request.data.get("team")

        if not names or not isinstance(names, list):
            return Response({"error": "'names' must be a list of full names."}, status=400)
        if not team or not isinstance(team, str):
            return Response({"error": "'team' must be a string."}, status=400)

        def normalize_name(name):
            normalized = unicodedata.normalize("NFD", name)
            ascii_str = re.sub(r"[\u0300-\u036f]", "", normalized)
            return re.sub(r"[^a-zA-Z0-9]", "", ascii_str).lower()

        created_users = []
        skipped_users = []

        for full_name in names:
            username = normalize_name(full_name)
            if User.objects.filter(username=username).exists():
                skipped_users.append(username)
                continue

            serializer = UserCreateSerializer(data={"username": username, "team": team})
            if serializer.is_valid():
                serializer.save()
            created_users.append(username)

        return Response({
            "created": created_users,
            "skipped": skipped_users,
            "total_created": len(created_users),
            "message": "Users seeded successfully."
        }, status=201)