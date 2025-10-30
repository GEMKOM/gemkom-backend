import django_filters
from .models import CncTask
from django.db.models import Count

class CncTaskFilter(django_filters.FilterSet):
    """
    Filters for the CncTask model.
    """
    key = django_filters.CharFilter(lookup_expr='exact')
    name = django_filters.CharFilter(lookup_expr='icontains')
    nesting_id = django_filters.CharFilter(lookup_expr='icontains')
    material = django_filters.CharFilter(lookup_expr='icontains')
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')
    has_timer = django_filters.BooleanFilter(method='filter_has_timer')

    def filter_has_timer(self, queryset, name, value):
        queryset = queryset.annotate(timer_count=Count('timers'))
        if value:
            return queryset.filter(timer_count__gt=0)
        else:
            return queryset.filter(timer_count=0)

    class Meta:
        model = CncTask
        fields = [
            'key',
            'name',
            'nesting_id',
            'material',
            'in_plan',
            'is_hold_task',
            'machine_fk',
            'has_timer',
            'thickness_mm'
        ]