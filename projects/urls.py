from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CustomerViewSet, JobOrderViewSet,
    DepartmentTaskTemplateViewSet, JobOrderDepartmentTaskViewSet
)

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'job-orders', JobOrderViewSet)
router.register(r'task-templates', DepartmentTaskTemplateViewSet)
router.register(r'department-tasks', JobOrderDepartmentTaskViewSet)

urlpatterns = [
    path('', include(router.urls)),
]

# The router will automatically create the following URL patterns:
#
# Customers:
# GET/POST       /projects/customers/                    - List/Create customers
# GET/PUT/DELETE /projects/customers/{id}/               - Retrieve/Update/Delete customer
# GET            /projects/customers/?search=            - Search customers
# GET            /projects/customers/?is_active=true     - Filter by active status
# GET            /projects/customers/?show_inactive=true - Include inactive customers
#
# Job Orders:
# GET/POST       /projects/job-orders/                   - List/Create job orders
# GET/PUT/DELETE /projects/job-orders/{job_no}/          - Retrieve/Update/Delete job order
# GET            /projects/job-orders/?search=           - Search job orders
# GET            /projects/job-orders/?status=active     - Filter by status
# GET            /projects/job-orders/?status__in=active,draft - Filter by multiple statuses
# GET            /projects/job-orders/?priority=urgent   - Filter by priority
# GET            /projects/job-orders/?customer=1        - Filter by customer ID
# GET            /projects/job-orders/?parent__isnull=true - Get root job orders only
# GET            /projects/job-orders/?root_only=true    - Get root job orders only (custom)
#
# Job Order Actions:
# POST           /projects/job-orders/{job_no}/start/    - Start job (draft -> active)
# POST           /projects/job-orders/{job_no}/complete/ - Complete job
# POST           /projects/job-orders/{job_no}/hold/     - Put job on hold
# POST           /projects/job-orders/{job_no}/resume/   - Resume from hold
# POST           /projects/job-orders/{job_no}/cancel/   - Cancel job
# GET            /projects/job-orders/{job_no}/hierarchy/ - Get full hierarchy tree
#
# Choices:
# GET            /projects/job-orders/status_choices/    - Get status options
# GET            /projects/job-orders/priority_choices/  - Get priority options
