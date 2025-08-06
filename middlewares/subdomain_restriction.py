# your_app/middlewares/subdomain_restriction.py
from django.http import JsonResponse

class SubdomainRestrictionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        host = request.get_host()

        if user.is_authenticated and not user.is_superuser and hasattr(user, "profile"):
            work_location = user.profile.work_location  # e.g., "office" or "workshop"

            if host.startswith("ofis.") and work_location != "office":
                return JsonResponse({"error": "Workshop employees are not allowed to access ofis.gemcore.com.tr."}, status=403)

            if host.startswith("saha.") and work_location != "workshop":
                return JsonResponse({"error": "Office employees are not allowed to access saha.gemcore.com.tr."}, status=403)

        return self.get_response(request)
