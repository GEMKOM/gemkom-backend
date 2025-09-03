# overtime/filters.py
import django_filters
from .models import OvertimeRequest

class OvertimeRequestFilter(django_filters.FilterSet):
    start_at__gte = django_filters.DateTimeFilter(field_name="start_at", lookup_expr="gte")
    start_at__lte = django_filters.DateTimeFilter(field_name="start_at", lookup_expr="lte")
    end_at__gte = django_filters.DateTimeFilter(field_name="end_at", lookup_expr="gte")
    end_at__lte = django_filters.DateTimeFilter(field_name="end_at", lookup_expr="lte")

    requester = django_filters.NumberFilter(field_name="requester_id")
    user = django_filters.NumberFilter(field_name="entries__user_id")  # filter by a specific user in entries
    status = django_filters.CharFilter(field_name="status", lookup_expr="exact")
    team = django_filters.CharFilter(field_name="team", lookup_expr="exact")

    class Meta:
        model = OvertimeRequest
        fields = ["status", "team", "requester"]
