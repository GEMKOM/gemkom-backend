import base64
import urllib.parse
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


class JiraProxyView(APIView):
    def dispatch(self, request, *args, **kwargs):
        # Optional: allow unauthenticated access if needed
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.proxy(request)

    def post(self, request):
        return self.proxy(request)

    def proxy(self, request):
        proxy_url = request.query_params.get("url")
        if not proxy_url:
            return Response({"error": "Missing ?url="}, status=400)

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

            return Response(
                data=response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
                status=response.status_code
            )
        except Exception as e:
            return Response({"error": str(e)}, status=500)