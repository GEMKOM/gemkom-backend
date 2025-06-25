from django.urls import path
from .views import AdminCreateUserView, CurrentUserView, ForcedPasswordResetView, UserListView

urlpatterns = [
    path('', UserListView.as_view(), name='user-list'),
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path('admin/create-user/', AdminCreateUserView.as_view(), name='admin-create-user'),
    path("reset-password/", ForcedPasswordResetView.as_view(), name="forced-password-reset"),
]
