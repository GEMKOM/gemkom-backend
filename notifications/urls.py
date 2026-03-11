from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceViewSet, NotificationRouteViewSet, NotificationViewSet, SendEmailTaskView

# Separate routers so the empty-prefix NotificationViewSet doesn't swallow /routes/ and /preferences/
notification_router = DefaultRouter()
notification_router.register(r'', NotificationViewSet, basename='notification')

aux_router = DefaultRouter()
aux_router.register(r'preferences', NotificationPreferenceViewSet, basename='notification-preference')
aux_router.register(r'routes', NotificationRouteViewSet, basename='notification-route')

urlpatterns = [
    # Internal Cloud Tasks callback
    path('tasks/send-email/', SendEmailTaskView.as_view(), name='notification-send-email-task'),
    # Preferences and routes must come before the empty-prefix router catch-all
    path('', include(aux_router.urls)),
    path('', include(notification_router.urls)),
]
