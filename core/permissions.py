from rest_framework.permissions import BasePermission
from django.conf import settings

class IsJiraAutomation(BasePermission):
    def has_permission(self, request, view):
        auth = request.headers.get("Authorization", "")
        return auth == f"Bearer {settings.JIRA_AUTOMATION_TOKEN}"
