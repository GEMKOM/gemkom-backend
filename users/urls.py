from django.urls import path
from .views import (
    AdminBulkCreateUsers, AdminListResetRequestsView, AdminResetPasswordView,
    CurrentUserView, ForcedPasswordResetView,
    PasswordResetRequestView, UserViewSet, UserWageRateListView,
    WageRateDetailView, WageRateListCreateView, UserPermissionsView,
    UserPermissionDetailView, UserPermissionOverrideView,
    UserPermissionsMatrixView, PermissionListView,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')

# Explicit paths must be listed BEFORE router.urls because the DefaultRouter
# registered on r'' generates a broad {pk}/ detail pattern that would otherwise
# swallow slug-like paths such as "permissions/matrix/".
urlpatterns = [
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path("me/permissions/", UserPermissionsView.as_view(), name="user-permissions"),
    path('admin/bulk-create-user/', AdminBulkCreateUsers.as_view(), name='admin-create-user-bulk'),
    path("reset-password/", ForcedPasswordResetView.as_view(), name="forced-password-reset"),
    path("forgot-password/list/", AdminListResetRequestsView.as_view(), name="admin_list_pw_resets"),
    path("forgot-password/request/", PasswordResetRequestView.as_view(), name="pw_reset_request"),
    path("forgot-password/<int:user_id>", AdminResetPasswordView.as_view(), name="admin_reset_user_pw"),
    path("wages/", WageRateListCreateView.as_view(), name="wage-list-create"),
    path("wages/<int:pk>/", WageRateDetailView.as_view(), name="wage-detail"),
    path("<int:user_id>/wages/", UserWageRateListView.as_view(), name="user-wage-list"),
    # Permission management
    path("permissions/", PermissionListView.as_view(), name="permissions-list"),
    path("permissions/matrix/", UserPermissionsMatrixView.as_view(), name="permissions-matrix"),
    path("<int:user_id>/permissions/", UserPermissionDetailView.as_view(), name="user-permission-detail"),
    path("<int:user_id>/permission-overrides/", UserPermissionOverrideView.as_view(), name="user-permission-overrides"),
    path("<int:user_id>/permission-overrides/<str:codename>/", UserPermissionOverrideView.as_view(), name="user-permission-override-detail"),
] + router.urls
