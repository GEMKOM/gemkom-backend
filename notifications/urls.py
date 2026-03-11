from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceViewSet, NotificationViewSet, SendEmailTaskView

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')
router.register(r'preferences', NotificationPreferenceViewSet, basename='notification-preference')

urlpatterns = [
    # Internal Cloud Tasks callback — must come before the router catch-all
    path('tasks/send-email/', SendEmailTaskView.as_view(), name='notification-send-email-task'),
    path('', include(router.urls)),
]
