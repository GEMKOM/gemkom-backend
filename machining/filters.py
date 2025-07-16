import django_filters
from .models import Task

class TaskFilter(django_filters.FilterSet):
    key = django_filters.CharFilter(lookup_expr='exact')
    name = django_filters.CharFilter(lookup_expr='icontains')
    job_no = django_filters.CharFilter(lookup_expr='icontains')
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')

    completion_date = django_filters.DateFilter(field_name='completion_date')  # exact match
    completion_date__gte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='gte')  # after or on
    completion_date__lte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='lte')  # before or on

    class Meta:
        model = Task
        fields = ['key', 'name', 'job_no', 'position_no', 'image_no', 'completed_by', 'completion_date', 'completion_date__gte', 'completion_date__lte', 'machine_fk']
