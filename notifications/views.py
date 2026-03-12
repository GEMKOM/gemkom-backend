from __future__ import annotations

import json
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views import View
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response

from core.emails import send_plain_email

from .models import Notification, NotificationPreference, NotificationRoute
from .serializers import NotificationPreferenceSerializer, NotificationRouteSerializer, NotificationSerializer
from .service import NOTIFICATION_DEFAULTS

logger = logging.getLogger(__name__)


# =============================================================================
# In-app notifications
# =============================================================================

class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    List and manage in-app notifications for the authenticated user.

    GET  /notifications/                        — paginated list
    GET  /notifications/?is_read=false          — unread only
    GET  /notifications/?notification_type=...  — filter by type
    POST /notifications/{id}/mark_read/         — mark one as read
    POST /notifications/mark_all_read/          — mark all as read
    GET  /notifications/unread_count/           — {"count": N}
    """
    serializer_class   = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, OrderingFilter]
    filterset_fields   = {
        'is_read':           ['exact'],
        'notification_type': ['exact'],
    }
    ordering_fields = ['created_at', 'is_read']
    ordering        = ['is_read', '-created_at']

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        updated = Notification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return Response({
            'status': 'success',
            'message': f'{updated} bildirim okundu olarak işaretlendi.',
        })

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'count': count})


# =============================================================================
# Notification preferences
# =============================================================================

class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    """
    Manage per-user notification preferences.

    GET   /notifications/preferences/                        — list all types, defaults filled in
    PUT   /notifications/preferences/{notification_type}/    — upsert one preference
    PATCH /notifications/preferences/{notification_type}/    — upsert one preference (partial)
    POST  /notifications/preferences/reset/                  — delete all rows (revert to defaults)
    """
    serializer_class   = NotificationPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field       = 'notification_type'
    http_method_names  = ['get', 'put', 'patch', 'post', 'head', 'options']

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        """
        Return all notification types with current preferences.
        Types that have no saved row are returned with default values and is_default=True.
        """
        existing = {
            p.notification_type: p
            for p in self.get_queryset()
        }
        result = []
        for ntype, (email_default, inapp_default) in NOTIFICATION_DEFAULTS.items():
            if ntype in existing:
                pref = existing[ntype]
                serializer = self.get_serializer(pref)
                data = dict(serializer.data)
                data['is_default'] = False
            else:
                choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
                data = {
                    'notification_type': ntype,
                    'notification_type_display': choices.get(ntype, ntype),
                    'send_email': email_default,
                    'send_in_app': inapp_default,
                    'is_default': True,
                }
            result.append(data)
        return Response(result)

    def update(self, request, *args, **kwargs):
        """Upsert: create the preference row if it doesn't exist yet."""
        partial = kwargs.pop('partial', False)
        notification_type = kwargs.get('notification_type') or self.kwargs.get('notification_type')
        if notification_type not in NOTIFICATION_DEFAULTS:
            return Response({'detail': 'Unknown notification type.'}, status=status.HTTP_400_BAD_REQUEST)
        instance, _ = NotificationPreference.objects.get_or_create(
            user=request.user,
            notification_type=notification_type,
        )
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        data = dict(serializer.data)
        data['is_default'] = False
        return Response(data)

    @action(detail=False, methods=['post'])
    def reset(self, request):
        """Delete all preference rows for the user, reverting to defaults."""
        deleted, _ = NotificationPreference.objects.filter(user=request.user).delete()
        return Response({
            'status': 'success',
            'message': f'{deleted} tercih silindi. Varsayılan ayarlar geçerli.',
        })


# =============================================================================
# Notification routes (admin-configurable recipient lists)
# =============================================================================

class NotificationRouteViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Admin-configurable recipient lists for specific event types.

    GET  /notifications/routes/                     — list all routable event types
    GET  /notifications/routes/{notification_type}/ — detail for one type
    PATCH /notifications/routes/{notification_type}/ — update users/enabled
    """
    serializer_class   = NotificationRouteSerializer
    permission_classes = [permissions.IsAdminUser]
    lookup_field       = 'notification_type'

    def get_queryset(self):
        return NotificationRoute.objects.prefetch_related('users')

    def _get_or_create(self, notification_type):
        route, _ = NotificationRoute.objects.get_or_create(
            notification_type=notification_type,
            defaults={'enabled': True},
        )
        return route

    def list(self, request):
        choices = dict(Notification.NOTIFICATION_TYPE_CHOICES)
        result = []
        existing = {r.notification_type: r for r in self.get_queryset()}
        for ntype in NotificationRoute.ROUTABLE_TYPES:
            route = existing.get(ntype) or NotificationRoute(notification_type=ntype, enabled=True)
            data = self.get_serializer(route).data
            result.append(data)
        return Response(result)

    def retrieve(self, request, notification_type=None):
        route = self._get_or_create(notification_type)
        return Response(self.get_serializer(route).data)

    def partial_update(self, request, notification_type=None):
        if notification_type not in NotificationRoute.ROUTABLE_TYPES:
            return Response({'detail': 'Not a routable notification type.'}, status=status.HTTP_400_BAD_REQUEST)
        route = self._get_or_create(notification_type)
        serializer = self.get_serializer(route, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(self.get_serializer(route).data)


# =============================================================================
# Cloud Tasks callback — internal endpoint
# =============================================================================

def _verify_oidc_token(request):
    """
    Verify the Google-signed OIDC token attached by Cloud Tasks.
    Raises PermissionDenied if the token is missing or invalid.

    Skipped when USE_CLOUD_TASKS=False (local dev) or when the token
    belongs to the configured service account.
    """
    if not getattr(settings, 'USE_CLOUD_TASKS', True):
        return  # skip verification in local dev

    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise PermissionDenied('Missing OIDC token')

    token = auth_header[7:]
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.CLOUD_RUN_SERVICE_URL,
        )
    except Exception as exc:
        logger.warning('OIDC token verification failed: %s', exc)
        raise PermissionDenied('Invalid OIDC token')


class SendEmailTaskView(View):
    """
    POST /notifications/tasks/send-email/

    Called by Google Cloud Tasks. Protected by OIDC token verification.
    Sends the email and marks the linked Notification as emailed.
    """

    def post(self, request):
        _verify_oidc_token(request)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        to              = data.get('to', '')
        subject         = data.get('subject', '')
        body            = data.get('body', '')
        notification_id = data.get('notification_id')

        if not to or not subject:
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        try:
            send_plain_email(subject=subject, body=body, to=to)
            if notification_id:
                Notification.objects.filter(pk=notification_id).update(
                    is_emailed=True,
                    emailed_at=timezone.now(),
                    email_error='',
                )
        except Exception as exc:
            logger.exception('SendEmailTaskView: failed to send email to %s', to)
            if notification_id:
                Notification.objects.filter(pk=notification_id).update(
                    email_error=str(exc),
                )
            # Return 5xx so Cloud Tasks retries the task
            return JsonResponse({'error': str(exc)}, status=500)

        return HttpResponse(status=200)
