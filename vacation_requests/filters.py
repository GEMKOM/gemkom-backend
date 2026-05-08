import django_filters
from .models import VacationRequest


class VacationRequestFilter(django_filters.FilterSet):
    start_date_from = django_filters.DateFilter(field_name="start_date", lookup_expr="gte")
    start_date_to   = django_filters.DateFilter(field_name="start_date", lookup_expr="lte")
    end_date_from   = django_filters.DateFilter(field_name="end_date",   lookup_expr="gte")
    end_date_to     = django_filters.DateFilter(field_name="end_date",   lookup_expr="lte")

    class Meta:
        model  = VacationRequest
        fields = ["status", "leave_type", "requester", "team"]
