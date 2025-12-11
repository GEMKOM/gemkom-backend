import django_filters
from .models import PurchaseRequest, Item

class ItemFilter(django_filters.FilterSet):
    code = django_filters.CharFilter(field_name="code", lookup_expr="icontains")
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Item
        fields = {
            "code": ["icontains", "exact", "startswith"],
            "name": ["icontains", "startswith"],
            "item_type": ["exact"],
        }

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
