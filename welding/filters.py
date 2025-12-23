import django_filters
from .models import WeldingTimeEntry


class WeldingTimeEntryFilter(django_filters.FilterSet):
    """
    FilterSet for WeldingTimeEntry to support various query parameters.
    """
    # Exact match filters
    employee = django_filters.NumberFilter(field_name='employee__id')
    job_no = django_filters.CharFilter(lookup_expr='icontains')

    # Date filters
    date = django_filters.DateFilter(field_name='date', lookup_expr='exact')
    date_after = django_filters.DateFilter(field_name='date', lookup_expr='gte')
    date_before = django_filters.DateFilter(field_name='date', lookup_expr='lte')

    # Hours filters
    hours_min = django_filters.NumberFilter(field_name='hours', lookup_expr='gte')
    hours_max = django_filters.NumberFilter(field_name='hours', lookup_expr='lte')

    # Overtime type filter
    overtime_type = django_filters.ChoiceFilter(
        choices=WeldingTimeEntry.OVERTIME_TYPE_CHOICES
    )

    # Username filter (for convenience)
    employee_username = django_filters.CharFilter(
        field_name='employee__username',
        lookup_expr='icontains'
    )

    # Description filter
    description = django_filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = WeldingTimeEntry
        fields = [
            'employee',
            'employee_username',
            'job_no',
            'date',
            'date_after',
            'date_before',
            'hours_min',
            'hours_max',
            'overtime_type',
            'description',
        ]
