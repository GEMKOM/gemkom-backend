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
from .serializers import AdminUserUpdateSerializer, CurrentUserUpdateSerializer, PasswordResetSerializer, PublicUserSerializer, UserCreateSerializer, UserListSerializer
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.viewsets import ModelViewSet

class UserViewSet(ModelViewSet):
    queryset = User.objects.all().select_related('profile').order_by('username')
    serializer_class = UserListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = UserFilter

    def get_queryset(self):
        user = self.request.user
        qs = User.objects.select_related('profile').order_by('username')

        if not user.is_authenticated:
            return qs.filter(profile__work_location='workshop')

        if user.is_superuser or getattr(user.profile, 'is_admin', False):
            return qs

        if getattr(user.profile, 'work_location', None) == 'office':
            return qs

        return qs.filter(profile__work_location='workshop')


    def get_permissions(self):
        if self.action == 'list':
            return []
        return [IsAdmin()]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AdminUserUpdateSerializer
        elif self.action == 'list':
            user = self.request.user
            if not user.is_authenticated:
                return PublicUserSerializer
            if user.is_superuser or getattr(user.profile, 'is_admin', False):
                return UserListSerializer
            if getattr(user.profile, 'work_location', None) == 'office':
                return UserListSerializer
            return PublicUserSerializer
        return UserListSerializer


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        serializer = UserListSerializer(request.user)
        return Response(serializer.data)
    
    def put(self, request):
        user = request.user
        is_admin_user = user.is_superuser or getattr(user.profile, "is_admin", False)

        if is_admin_user:
            serializer_class = AdminUserUpdateSerializer
        else:
            serializer_class = CurrentUserUpdateSerializer

        serializer = serializer_class(user, data=request.data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "User updated successfully."})
        
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
    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.TEAM_CHOICES
        ])
    
class OccupationChoicesView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.OCCUPATION_CHOICES
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