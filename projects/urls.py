from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)

urlpatterns = [
    path('', include(router.urls)),
]

# The router will automatically create the following URL patterns:
#
# Customers:
# GET/POST       /api/projects/customers/           - List/Create customers
# GET/PUT/DELETE /api/projects/customers/{id}/      - Retrieve/Update/Delete customer
# GET            /api/projects/customers/?search=   - Search customers by code, name, etc.
# GET            /api/projects/customers/?is_active=true - Filter by active status
# GET            /api/projects/customers/?show_inactive=true - Include inactive customers
