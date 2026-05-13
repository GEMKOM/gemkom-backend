from __future__ import annotations

from django.contrib.auth.models import User
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsAdmin, user_has_role_perm

from .models import Position, UserGroup
from .serializers import (
    PositionDetailSerializer,
    PositionHolderSerializer,
    PositionSerializer,
    PositionTreeSerializer,
    PositionWriteSerializer,
    UserGroupDetailSerializer,
    UserGroupSerializer,
    UserGroupWriteSerializer,
)


class IsAdminOrHR(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.user.is_superuser or request.user.is_staff:
            return True
        return user_has_role_perm(request.user, 'manage_hr')


# =============================================================================
# Positions
# =============================================================================

class PositionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAdminOrHR]

    def get_queryset(self):
        qs = Position.objects.select_related('parent').prefetch_related('permissions', 'holders')
        dept = self.request.query_params.get('department_code')
        if dept:
            qs = qs.filter(department_code=dept)
        level = self.request.query_params.get('level')
        if level:
            qs = qs.filter(level=level)
        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PositionWriteSerializer
        return PositionSerializer


class PositionDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAdminOrHR]
    queryset = Position.objects.select_related('parent').prefetch_related('permissions')

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return PositionWriteSerializer
        return PositionDetailSerializer


class PositionPermissionsView(APIView):
    """
    GET   /positions/{id}/permissions/ — list codenames for this position
    PATCH /positions/{id}/permissions/ — set codenames for this position
    """
    permission_classes = [IsAdmin]

    def get(self, request, pk):
        position = Position.objects.filter(pk=pk).first()
        if not position:
            return Response({'error': 'Position not found.'}, status=404)
        return Response({'codenames': list(position.permissions.values_list('codename', flat=True))})

    def patch(self, request, pk):
        position = Position.objects.filter(pk=pk).first()
        if not position:
            return Response({'error': 'Position not found.'}, status=404)
        codenames = request.data.get('codenames', [])
        if not isinstance(codenames, list):
            return Response({'error': 'codenames must be a list.'}, status=400)
        from users.models import PermissionMeta
        perms = PermissionMeta.objects.filter(codename__in=codenames)
        position.permissions.set(perms)
        from organization.services import sync_user_permissions
        for profile in position.holders.select_related('user').filter(user__is_active=True):
            sync_user_permissions(profile.user, position)
        return Response({'codenames': list(position.permissions.values_list('codename', flat=True))})


class PositionHoldersView(APIView):
    """GET /positions/{id}/holders/ — users currently holding this position."""
    permission_classes = [IsAdminOrHR]

    def get(self, request, pk):
        position = Position.objects.filter(pk=pk).first()
        if not position:
            return Response({'error': 'Position not found.'}, status=404)
        users = User.objects.filter(
            profile__position=position,
            is_active=True,
        ).order_by('last_name', 'first_name')
        return Response(PositionHolderSerializer(users, many=True).data)


class PositionTreeView(APIView):
    """GET /positions/tree/ — full nested org tree."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        roots = Position.objects.filter(parent__isnull=True, is_active=True).order_by('level', 'title')
        return Response(PositionTreeSerializer(roots, many=True).data)


# =============================================================================
# UserGroups
# =============================================================================

class UserGroupListCreateView(generics.ListCreateAPIView):
    """
    GET  /organization/groups/   — list all groups (any authenticated user)
    POST /organization/groups/   — create group (admin only)
    """
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return UserGroup.objects.prefetch_related('positions').order_by('name')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return UserGroupWriteSerializer
        return UserGroupSerializer


class UserGroupDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /organization/groups/{id}/   — detail with members (admin only)
    PATCH  /organization/groups/{id}/   — update name/description/is_active (admin only)
    DELETE /organization/groups/{id}/   — delete (admin only)
    """
    permission_classes = [IsAdmin]
    queryset = UserGroup.objects.prefetch_related('positions')

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserGroupWriteSerializer
        return UserGroupDetailSerializer


class UserGroupPositionsView(APIView):
    """
    PATCH /organization/groups/{pk}/positions/
    Body: {"position_ids": [1, 2, 3, ...]}
    Replaces the entire position list. Admin only.
    """
    permission_classes = [IsAdmin]

    def patch(self, request, pk):
        group = generics.get_object_or_404(UserGroup, pk=pk)
        position_ids = request.data.get('position_ids')
        if not isinstance(position_ids, list):
            return Response({'detail': 'position_ids must be a list.'}, status=status.HTTP_400_BAD_REQUEST)
        group.positions.set(Position.objects.filter(id__in=position_ids))
        return Response(UserGroupDetailSerializer(group).data)
