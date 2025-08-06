# your_app/middlewares/subdomain_restriction.py
from django.http import JsonResponse

class SubdomainRestrictionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ✅ Allow CORS preflight requests
        if request.method == "OPTIONS":
            return self.get_response(request)

        # ✅ Normalize host (remove port if any)
        host = request.headers.get("X-Subdomain", "").split(":")[0]

        # ✅ Ensure request.user is safe to access
        user = getattr(request, "user", None)

        if user and user.is_authenticated and not user.is_superuser:
            profile = getattr(user, "profile", None)

            if profile:
                work_location = profile.work_location  # "office" or "workshop"

                # 🚫 Enforce domain rules
                if host.startswith("ofis.") and work_location != "office":
                    return JsonResponse({"error": "You do not have access to this page."}, status=403)

                if host.startswith("saha.") and work_location != "workshop":
                    return JsonResponse({"error": "You do not have access to this page."}, status=403)

        return self.get_response(request)
