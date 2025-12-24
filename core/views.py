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

import os
import requests
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from rest_framework.views import APIView
from .models import CurrencyRateSnapshot

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
        host = request.headers.get("X-Subdomain", "").split(":")[0]

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
        
        if (not jira_email or not jira_token) and not user.is_admin:
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


class LatestCurrencyRatesView(APIView):
    authentication_classes = []   # adjust if you need auth
    permission_classes = []       # adjust if you need auth

    def get(self, request):
        if not settings.FREECURRENCYAPI_KEY:
            return HttpResponse("FREECURRENCYAPI_KEY not set", status=500)

        today = timezone.now().date()

        # 1) Read today's snapshot
        snap = CurrencyRateSnapshot.objects.filter(date=today).first()
        if snap:
            return JsonResponse({
                "provider": snap.provider,
                "date": str(snap.date),
                "base": snap.base,
                "rates": snap.rates,
            })

        # 2) Not found → fetch, store, return
        try:
            res = requests.get(
                settings.CURRENCY_RATE_API_URL,
                params={"apikey": settings.FREECURRENCYAPI_KEY, "base_currency": settings.CURRENCY_FIXED_BASE},
                timeout=20
            )
            res.raise_for_status()
            payload = res.json()
            rates = payload.get("data") or {}
            if not rates:
                return HttpResponse("No data from provider", status=502)
        except Exception as e:
            return HttpResponse(f"Fetch failed: {e}", status=502)

        snap = CurrencyRateSnapshot.objects.create(
            date=today,
            base=settings.CURRENCY_FIXED_BASE,
            rates=rates,
        )
        return JsonResponse({
            "provider": snap.provider,
            "date": str(snap.date),
            "base": snap.base,
            "rates": snap.rates,
        })


class CombinedJobCostListView(APIView):
    """
    GET /reports/combined-job-costs/?job_no=283

    Returns combined job costs from both machining (timers) and welding (time entries).
    Aggregates by job_no showing hours from both departments.

    Response:
    {
      "count": 2,
      "results": [
        {
          "job_no": "001-23",
          "machining": {
            "hours": {
              "weekday_work": 100.0,
              "after_hours": 20.0,
              "sunday": 5.0
            },
            "total_hours": 125.0
          },
          "welding": {
            "hours": {
              "regular": 80.0,
              "after_hours": 15.0,
              "holiday": 3.0
            },
            "total_hours": 98.0
          },
          "combined_total_hours": 223.0,
          "updated_at": "2024-01-15T12:00:00Z"
        }
      ]
    }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db.models import Sum, Max
        from machining.models import JobCostAgg
        from welding.models import WeldingJobCostAgg

        job_no = (request.query_params.get("job_no") or "").strip()
        ordering = (request.query_params.get("ordering") or "-combined_total_cost").strip()

        # --- Get machining costs per job_no from pre-calculated aggregations ---
        machining_qs = JobCostAgg.objects.all()
        if job_no:
            machining_qs = machining_qs.filter(job_no_cached__icontains=job_no)

        machining_agg = (
            machining_qs.values("job_no_cached")
            .annotate(
                hours_ww=Sum("hours_ww"),
                hours_ah=Sum("hours_ah"),
                hours_su=Sum("hours_su"),
                cost_ww=Sum("cost_ww"),
                cost_ah=Sum("cost_ah"),
                cost_su=Sum("cost_su"),
                total_cost=Sum("total_cost"),
                updated_at=Max("updated_at"),
            )
        )

        machining_jobs = {
            row['job_no_cached']: {
                'weekday_work': float(row['hours_ww'] or 0),
                'after_hours': float(row['hours_ah'] or 0),
                'sunday': float(row['hours_su'] or 0),
                'cost_ww': float(row['cost_ww'] or 0),
                'cost_ah': float(row['cost_ah'] or 0),
                'cost_su': float(row['cost_su'] or 0),
                'total_cost': float(row['total_cost'] or 0),
                'updated_at': row['updated_at']
            }
            for row in machining_agg
        }

        # --- Get welding costs per job_no from pre-calculated aggregations ---
        welding_qs = WeldingJobCostAgg.objects.all()
        if job_no:
            welding_qs = welding_qs.filter(job_no__icontains=job_no)

        welding_agg = (
            welding_qs.values("job_no")
            .annotate(
                hours_regular=Sum("hours_regular"),
                hours_after_hours=Sum("hours_after_hours"),
                hours_holiday=Sum("hours_holiday"),
                cost_regular=Sum("cost_regular"),
                cost_after_hours=Sum("cost_after_hours"),
                cost_holiday=Sum("cost_holiday"),
                total_cost=Sum("total_cost"),
                updated_at=Max("updated_at"),
            )
        )

        welding_jobs = {
            row['job_no']: {
                'regular': float(row['hours_regular'] or 0),
                'after_hours': float(row['hours_after_hours'] or 0),
                'holiday': float(row['hours_holiday'] or 0),
                'cost_regular': float(row['cost_regular'] or 0),
                'cost_after_hours': float(row['cost_after_hours'] or 0),
                'cost_holiday': float(row['cost_holiday'] or 0),
                'total_cost': float(row['total_cost'] or 0),
                'updated_at': row['updated_at']
            }
            for row in welding_agg
        }

        # --- Combine results ---
        all_job_nos = set(machining_jobs.keys()) | set(welding_jobs.keys())

        results = []
        for j in all_job_nos:
            m_data = machining_jobs.get(j, {
                "weekday_work": 0.0,
                "after_hours": 0.0,
                "sunday": 0.0,
                "cost_ww": 0.0,
                "cost_ah": 0.0,
                "cost_su": 0.0,
                "total_cost": 0.0,
                "updated_at": None
            })
            w_data = welding_jobs.get(j, {
                'regular': 0.0,
                'after_hours': 0.0,
                'holiday': 0.0,
                'cost_regular': 0.0,
                'cost_after_hours': 0.0,
                'cost_holiday': 0.0,
                'total_cost': 0.0,
                'updated_at': None
            })

            combined_total_cost = m_data['total_cost'] + w_data['total_cost']
            combined_total_hours = (
                m_data['weekday_work'] + m_data['after_hours'] + m_data['sunday'] +
                w_data['regular'] + w_data['after_hours'] + w_data['holiday']
            )

            # Get most recent updated_at
            updated_dates = [d for d in [m_data['updated_at'], w_data['updated_at']] if d is not None]
            most_recent = max(updated_dates) if updated_dates else None

            item = {
                "job_no": j,
                "machining": {
                    "hours": {
                        "weekday_work": round(m_data["weekday_work"], 2),
                        "after_hours": round(m_data["after_hours"], 2),
                        "sunday": round(m_data["sunday"], 2),
                    },
                    "costs": {
                        "weekday_work": round(m_data["cost_ww"], 2),
                        "after_hours": round(m_data["cost_ah"], 2),
                        "sunday": round(m_data["cost_su"], 2),
                    },
                    "total_cost": round(m_data["total_cost"], 2)
                } if m_data['total_cost'] > 0 else None,
                "welding": {
                    "hours": {
                        "regular": round(w_data['regular'], 2),
                        "after_hours": round(w_data['after_hours'], 2),
                        "holiday": round(w_data['holiday'], 2),
                    },
                    "costs": {
                        "regular": round(w_data['cost_regular'], 2),
                        "after_hours": round(w_data['cost_after_hours'], 2),
                        "holiday": round(w_data['cost_holiday'], 2),
                    },
                    "total_cost": round(w_data['total_cost'], 2)
                } if w_data['total_cost'] > 0 else None,
                "combined_total_cost": round(combined_total_cost, 2),
                "combined_total_hours": round(combined_total_hours, 2),
                "currency": "EUR",
                "updated_at": most_recent,
            }
            results.append(item)

        # Sort results
        if ordering == "job_no":
            results.sort(key=lambda x: x['job_no'])
        elif ordering == "-job_no":
            results.sort(key=lambda x: x['job_no'], reverse=True)
        elif ordering == "combined_total_cost":
            results.sort(key=lambda x: x['combined_total_cost'])
        elif ordering == "combined_total_hours":
            results.sort(key=lambda x: x['combined_total_hours'])
        elif ordering == "-combined_total_hours":
            results.sort(key=lambda x: x['combined_total_hours'], reverse=True)
        else:  # Default: -combined_total_cost
            results.sort(key=lambda x: x['combined_total_cost'], reverse=True)

        return Response({"count": len(results), "results": results}, status=200)