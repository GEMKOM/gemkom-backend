from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response

from users.models import UserProfile
from users.permissions import IsAdmin
from .serializers import PasswordResetSerializer, UserCreateSerializer, UserListSerializer
from rest_framework.permissions import IsAuthenticated

class UserListView(APIView):
    def get(self, request):
        users = User.objects.all().select_related('profile')
        serializer = UserListSerializer(users, many=True)
        return Response(serializer.data)

class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserListSerializer(request.user)
        return Response(serializer.data)
    
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
    permission_classes = [IsAdmin]  # Optional

    def get(self, request):
        return Response([
            {"value": k, "label": v} for k, v in UserProfile.TEAM_CHOICES
        ])