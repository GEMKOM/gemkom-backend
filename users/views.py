from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated  # Optional
from .serializers import UserListSerializer


class LoginView(APIView):
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"error": "Kullanıcı bulunamadı."}, status=status.HTTP_404_NOT_FOUND)

        # First time login - user has no password yet
        if not user.has_usable_password():
            user.set_password(password)
            user.save()
            return Response({"message": "Şifre oluşturuldu. Giriş başarılı."}, status=status.HTTP_200_OK)

        # Regular login
        user = authenticate(username=username, password=password)
        if user:
            return Response({"message": "Giriş başarılı."}, status=status.HTTP_200_OK)

        return Response({"error": "Şifre hatalı."}, status=status.HTTP_401_UNAUTHORIZED)




class UserListView(APIView):
    # permission_classes = [IsAuthenticated]  # Optional: Require login

    def get(self, request):
        users = User.objects.all().select_related('profile')
        serializer = UserListSerializer(users, many=True)
        return Response(serializer.data)
