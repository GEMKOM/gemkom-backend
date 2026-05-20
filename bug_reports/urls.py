from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import AgentProcessTaskView, BugReportViewSet

router = DefaultRouter()
router.register(r'', BugReportViewSet, basename='bug-report')

urlpatterns = [
    path('tasks/process/<int:bug_report_id>/', AgentProcessTaskView.as_view(), name='bug-report-agent-task'),
    path('', include(router.urls)),
]
