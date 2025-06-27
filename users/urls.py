from django.urls import path
from .views import AdminBulkCreateUsers, AdminCreateUserView, CurrentUserView, ForcedPasswordResetView, TeamChoicesView, UserListView

urlpatterns = [
    path('', UserListView.as_view(), name='user-list'),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path('admin/create-user/', AdminCreateUserView.as_view(), name='admin-create-user'),
    path('admin/bulk-create-user/', AdminBulkCreateUsers.as_view(), name='admin-create-user-bulk'),
    path("reset-password/", ForcedPasswordResetView.as_view(), name="forced-password-reset"),
    path("teams/", TeamChoicesView.as_view(), name="teams-list"),
]
