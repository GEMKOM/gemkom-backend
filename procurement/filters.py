import django_filters
from .models import PurchaseRequest

class PurchaseRequestFilter(django_filters.FilterSet):
    created_at__gte = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_at__lte = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = PurchaseRequest
        fields = {
            "status": ["exact"],
            "priority": ["exact"],
            "requestor": ["exact"],  # will filter by requestor id
            "request_number": ["icontains"],  # allow partial matches
        }
