from django.urls import path
from .views import DBTestView, JiraIssueCreatedWebhook, JiraProxyView, TimerNowView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("db-test/", DBTestView.as_view()),
    path("now/", TimerNowView.as_view()),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("jira/proxy/", JiraProxyView.as_view(), name="jira-proxy"),
    path('jira/issue-created/', JiraIssueCreatedWebhook.as_view(), name='jira-issue-created'),
]