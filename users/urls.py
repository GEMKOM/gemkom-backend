from django.urls import path
from .views import AdminBulkCreateUsers, AdminListResetRequestsView, AdminResetPasswordView, CurrentUserView, ForcedPasswordResetView, OccupationChoicesView, PasswordResetRequestView, TeamChoicesView, UserViewSet, UserWageRateListView, WageRateDetailView, WageRateListCreateView
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'', UserViewSet, basename='user')

urlpatterns = [
    path("me/", CurrentUserView.as_view(), name="current-user"),
    path('admin/bulk-create-user/', AdminBulkCreateUsers.as_view(), name='admin-create-user-bulk'),
    path("reset-password/", ForcedPasswordResetView.as_view(), name="forced-password-reset"),
    path("teams/", TeamChoicesView.as_view(), name="teams-list"),
    path("occupations/", OccupationChoicesView.as_view(), name="occupations-list"),
    path("forgot-password/list/", AdminListResetRequestsView.as_view(), name="admin_list_pw_resets"),
    path("forgot-password/request/", PasswordResetRequestView.as_view(), name="pw_reset_request"),
    path("forgot-password/<int:user_id>", AdminResetPasswordView.as_view(), name="admin_reset_user_pw"),
    path("wages/", WageRateListCreateView.as_view(), name="wage-list-create"),
    path("wages/<int:pk>/", WageRateDetailView.as_view(), name="wage-detail"),
    path("<int:user_id>/wages/", UserWageRateListView.as_view(), name="user-wage-list"),

]

urlpatterns += router.urls