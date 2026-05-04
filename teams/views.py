from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Team
from .serializers import TeamSerializer, TeamListSerializer


class TeamViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Team.objects.prefetch_related('members').select_related('foreman')
        include_inactive = self.request.query_params.get('include_inactive', '').lower() == 'true'
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return TeamListSerializer
        return TeamSerializer

    def destroy(self, request, *args, **kwargs):
        team = self.get_object()
        team.is_active = False
        team.save(update_fields=['is_active'])
        return Response(status=status.HTTP_204_NO_CONTENT)
