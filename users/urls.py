from django.urls import path
from .views import AdminBulkCreateUsers, CurrentUserView, ForcedPasswordResetView, OccupationChoicesView, TeamChoicesView, UserViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')

urlpatterns = [
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path('admin/bulk-create-user/', AdminBulkCreateUsers.as_view(), name='admin-create-user-bulk'),
    path("reset-password/", ForcedPasswordResetView.as_view(), name="forced-password-reset"),
    path("teams/", TeamChoicesView.as_view(), name="teams-list"),
    path("occupations/", OccupationChoicesView.as_view(), name="occupations-list"),
]

urlpatterns += router.urls