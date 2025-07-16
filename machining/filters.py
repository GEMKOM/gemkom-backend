import django_filters
from .models import Task

class TaskFilter(django_filters.FilterSet):
    key = django_filters.CharFilter(lookup_expr='exact')
    name = django_filters.CharFilter(lookup_expr='icontains')
    job_no = django_filters.CharFilter(lookup_expr='icontains')
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')

    completion_date = django_filters.DateFilter(field_name='completion_date')
    completion_date__gte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='gte')
    completion_date__lte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='lte')

    finish_time = django_filters.NumberFilter(field_name='finish_time')  # ✅
    finish_time__gte = django_filters.NumberFilter(field_name='finish_time', lookup_expr='gte')  # ✅
    finish_time__lte = django_filters.NumberFilter(field_name='finish_time', lookup_expr='lte')  # ✅

    class Meta:
        model = Task
        fields = [
            'key',
            'name',
            'job_no',
            'position_no',
            'image_no',
            'completed_by',
            'completion_date',
            'completion_date__gte',
            'completion_date__lte',
            'finish_time',
            'finish_time__gte',
            'finish_time__lte',
            'machine_fk',
        ]

