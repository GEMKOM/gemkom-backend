from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter

from .views import NotificationPreferenceViewSet, NotificationConfigViewSet, NotificationViewSet, SendEmailTaskView

notification_router = DefaultRouter()
notification_router.register(r'', NotificationViewSet, basename='notification')

# SimpleRouter has no API-root view, so it won't shadow the notification list at /notifications/
aux_router = SimpleRouter()
aux_router.register(r'preferences', NotificationPreferenceViewSet, basename='notification-preference')
aux_router.register(r'config', NotificationConfigViewSet, basename='notification-config')

urlpatterns = [
    # Internal Cloud Tasks callback
    path('tasks/send-email/', SendEmailTaskView.as_view(), name='notification-send-email-task'),
    # Preferences and routes must come before the empty-prefix router catch-all
    path('', include(aux_router.urls)),
    path('', include(notification_router.urls)),
]
