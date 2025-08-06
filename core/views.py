import base64
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import connection
from django.utils.timezone import now

from config import settings
import requests
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
import logging

from core.permissions import IsJiraAutomation
from machining.models import Task
from django.contrib.auth.models import User

from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@permission_classes([IsAuthenticated])
class DBTestView(APIView):
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version();")
                row = cursor.fetchone()
            return Response({"status": "success", "version": row[0]}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@permission_classes([IsAuthenticated])
class TimerNowView(APIView):
    def get(self, request):
        return Response({"now": int(now().timestamp() * 1000)})


class CustomTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        host = request.get_host().split(":")[0]  # strips :443 or :8000

        # You must extract username manually to get the user object before token creation
        username = request.data.get("username")
        user = User.objects.filter(username=username).first()

        if user and not user.is_superuser and hasattr(user, "profile"):
            work_location = user.profile.work_location  # adjust if needed

            # Restrict based on domain
            if host.startswith("ofis.") and work_location != "office":
                raise PermissionDenied("Workshop employees must use workshop.gemcore.com.tr to log in.")
            elif host.startswith("saha.") and work_location != "workshop":
                raise PermissionDenied("Office employees must use office.gemcore.com.tr to log in.")

        return super().post(request, *args, **kwargs)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # Or use your frontend URL for tighter security
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

class JiraProxyView(APIView):

    permission_classes = [IsAuthenticated]
    def dispatch(self, request, *args, **kwargs):
        # Allow preflight OPTIONS requests
        if request.method == "OPTIONS":
            return Response(status=204, headers=CORS_HEADERS)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.proxy(request)

    def post(self, request):
        return self.proxy(request)

    def proxy(self, request):
        proxy_url = request.query_params.get("url")
        if not proxy_url:
            return HttpResponse(
                content='{"error": "Missing ?url="}',
                status=400,
                content_type="application/json",
                headers=CORS_HEADERS
            )

        user = request.user
        profile = getattr(user, 'profile', None)

        jira_email = getattr(user, 'email', None)
        jira_token = getattr(profile, 'jira_api_token', None)
        
        if (not jira_email or not jira_token) and not (user.is_superuser or user.profile.is_admin):
            jira_email = settings.JIRA_EMAIL
            jira_token = settings.JIRA_API_TOKEN

        auth_str = f"{jira_email}:{jira_token}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()

        try:
            body = request.body if request.method != "GET" else None
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }

            response = requests.request(
                method=request.method,
                url=proxy_url,
                headers=headers,
                data=body
            )

            content_type = response.headers.get("content-type", "application/json")

            # Prepare headers
            response_headers = dict(CORS_HEADERS)
            response_headers["Content-Type"] = content_type

            # Handle 204 No Content explicitly
            if response.status_code == 204:
                return HttpResponse(
                    status=204,
                    headers=response_headers
                )

            return HttpResponse(
                content=response.content,
                status=response.status_code,
                headers=response_headers
            )

        except Exception as e:
            return HttpResponse(
                content=f'{{"error": "{str(e)}"}}',
                status=500,
                content_type="application/json",
                headers=CORS_HEADERS
            )

class JiraIssueCreatedWebhook(APIView):
    authentication_classes = []
    permission_classes = [IsJiraAutomation]

    def post(self, request):
        issue = request.data.get("issue", {})
        fields = issue.get("fields", {})
        key = issue.get("key")
        summary = fields.get("summary", "")

        # Optional: parse job_no, image_no, etc. from description or custom fields
        description = fields.get("description", "")
        job_no = fields.get("customfield_10117")  # Example custom field ID
        image_no = fields.get("customfield_10184")
        position_no = fields.get("customfield_10185")
        quantity = fields.get("customfield_10187")

        if not key:
            return Response({"error": "Missing issue key"}, status=400)

        Task.objects.update_or_create(
            key=key,
            defaults={
                "name": summary,
                "job_no": job_no,
                "image_no": image_no,
                "position_no": position_no,
                "quantity": quantity,
            }
        )

        return Response({"status": "Task created/updated"}, status=201)
