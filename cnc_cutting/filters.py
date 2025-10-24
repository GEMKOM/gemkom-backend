import django_filters
from .models import CncTask


class CncTaskFilter(django_filters.FilterSet):
    """
    Filters for the CncTask model.
    """
    name = django_filters.CharFilter(lookup_expr='icontains')
    nesting_id = django_filters.CharFilter(lookup_expr='icontains')
    material = django_filters.CharFilter(lookup_expr='icontains')
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')

    class Meta:
        model = CncTask
        fields = [
            'name',
            'nesting_id',
            'material',
            'in_plan',
            'is_hold_task',
        ]