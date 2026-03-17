# your_app/middlewares/subdomain_restriction.py
from django.http import JsonResponse
from users.permissions import user_has_role_perm

PORTAL_PERMISSION = {
    'office':   'office_access',
    'workshop': 'workshop_access',
}

class SubdomainRestrictionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS":
            return self.get_response(request)

        user = getattr(request, "user", None)
        portal = request.headers.get("X-Portal", "")
        required_perm = PORTAL_PERMISSION.get(portal)

        if user and user.is_authenticated and not user.is_superuser and required_perm:
            if not user_has_role_perm(user, required_perm):
                return JsonResponse({"error": "Bu portal için erişim izniniz yok."}, status=403)

        return self.get_response(request)
