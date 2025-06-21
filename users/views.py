from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import UserListSerializer

class UserListView(APIView):
    # permission_classes = [IsAuthenticated]  # Optional: Require login

    def get(self, request):
        users = User.objects.all().select_related('profile')
        serializer = UserListSerializer(users, many=True)
        return Response(serializer.data)
