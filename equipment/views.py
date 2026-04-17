from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import EquipmentItem, EquipmentCheckout
from .serializers import (
    EquipmentItemListSerializer,
    EquipmentItemDetailSerializer,
    EquipmentItemWriteSerializer,
    EquipmentCheckoutListSerializer,
    EquipmentCheckoutCreateSerializer,
    EquipmentCheckoutDetailSerializer,
)
from .filters import EquipmentItemFilter, EquipmentCheckoutFilter


class EquipmentItemViewSet(viewsets.ModelViewSet):
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = EquipmentItemFilter
    ordering_fields = ['code', 'name', 'category', 'asset_type', 'quantity']
    ordering = ['code']
    search_fields = ['code', 'name', 'description', 'category']

    def get_queryset(self):
        return EquipmentItem.objects.all()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return EquipmentItemWriteSerializer
        if self.action == 'list':
            return EquipmentItemListSerializer
        return EquipmentItemDetailSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'checkouts']:
            return [IsAuthenticated()]
        return [IsAdminUser()]

    def destroy(self, request, *args, **kwargs):
        item = self.get_object()
        item.is_active = False
        item.save(update_fields=['is_active', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def checkouts(self, request, pk=None):
        item = self.get_object()
        qs = item.checkouts.select_related(
            'checked_out_by', 'checked_in_by', 'job_order'
        ).order_by('-checked_out_at')
        page = self.paginate_queryset(qs)
        serializer = EquipmentCheckoutListSerializer(
            page if page is not None else qs, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class EquipmentCheckoutViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = EquipmentCheckoutFilter
    ordering_fields = ['checked_out_at', 'checked_in_at', 'item']
    ordering = ['-checked_out_at']
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return EquipmentCheckout.objects.select_related(
            'item', 'checked_out_by', 'checked_in_by', 'job_order'
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return EquipmentCheckoutCreateSerializer
        if self.action in ['list', 'my']:
            return EquipmentCheckoutListSerializer
        return EquipmentCheckoutDetailSerializer

    @action(detail=True, methods=['post'], url_path='return')
    def return_item(self, request, pk=None):
        checkout = self.get_object()
        if checkout.is_returned:
            return Response(
                {'detail': 'This checkout is already returned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        checked_in_by = request.user
        if 'checked_in_by' in request.data:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                checked_in_by = User.objects.get(pk=request.data['checked_in_by'])
            except User.DoesNotExist:
                return Response(
                    {'detail': f"User {request.data['checked_in_by']} not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        checkout.checked_in_at = timezone.now()
        checkout.checked_in_by = checked_in_by
        checkout.save(update_fields=['checked_in_at', 'checked_in_by', 'updated_at'])
        return Response(EquipmentCheckoutDetailSerializer(checkout).data)

    @action(detail=False, methods=['get'])
    def my(self, request):
        qs = self.get_queryset().filter(
            checked_out_by=request.user,
            checked_in_at__isnull=True,
        )
        page = self.paginate_queryset(qs)
        serializer = EquipmentCheckoutListSerializer(
            page if page is not None else qs, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
