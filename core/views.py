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


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # Or use your frontend URL for tighter security
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


class JiraProxyView(APIView):
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

        jira_email = settings.JIRA_EMAIL
        jira_token = settings.JIRA_API_TOKEN

        if isinstance(jira_token, tuple):
            jira_token = jira_token[0]

        auth_str = f"{jira_email}:{jira_token}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()

        try:
            # Determine Content-Type
            incoming_content_type = request.headers.get("Content-Type", "").lower()
            is_json = "application/json" in incoming_content_type
            is_form = "application/x-www-form-urlencoded" in incoming_content_type or "multipart/form-data" in incoming_content_type

            # Extract body accordingly
            if request.method == "GET":
                body = None
            elif is_json:
                body = request.body
            elif is_form:
                body = request.body  # already in appropriate encoded format
            else:
                body = request.body  # fallback for anything else

            headers = {
                "Authorization": f"Basic {encoded_auth}",
            }

            # Only set Content-Type if it's NOT multipart/form-data
            if not incoming_content_type.startswith("multipart/form-data"):
                headers["Content-Type"] = incoming_content_type

            response = requests.request(
                method=request.method,
                url=proxy_url,
                headers=headers,
                data=body,
            )

            content_type = response.headers.get("content-type", "application/json")

            # Prepare headers
            response_headers = dict(CORS_HEADERS)
            response_headers["Content-Type"] = content_type

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
