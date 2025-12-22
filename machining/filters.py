import django_filters
from .models import Task
from django.db.models import Count, F

class TaskFilter(django_filters.FilterSet):
    key = django_filters.CharFilter(lookup_expr='exact')
    name = django_filters.CharFilter(lookup_expr='icontains')
    job_no = django_filters.CharFilter(lookup_expr='icontains')
    position_no = django_filters.CharFilter(lookup_expr='icontains')
    image_no = django_filters.CharFilter(lookup_expr='icontains')
    created_by_username = django_filters.CharFilter(field_name='created_by__username', lookup_expr='icontains')

    machine_fk__isnull = django_filters.BooleanFilter(field_name='machine_fk', lookup_expr='isnull')
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')

    completion_date = django_filters.DateFilter(field_name='completion_date')
    completion_date__gte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='gte')
    completion_date__lte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='lte')

    finish_time = django_filters.DateFilter(field_name='finish_time')
    finish_time__gte = django_filters.DateFilter(field_name='finish_time', lookup_expr='gte')
    finish_time__lte = django_filters.DateFilter(field_name='finish_time', lookup_expr='lte')
    has_timer = django_filters.BooleanFilter(method='filter_has_timer')
    exceeded_estimated_hours = django_filters.BooleanFilter(method='filter_exceeded_estimated_hours')

    def filter_has_timer(self, queryset, name, value):
        queryset = queryset.annotate(timer_count=Count('timers'))
        if value:
            return queryset.filter(timer_count__gt=0)
        else:
            return queryset.filter(timer_count=0)
    
    def filter_exceeded_estimated_hours(self, queryset, name, value):
        if value:
            # The 'total_hours_spent' annotation is expected to be on the queryset from the view.
            return queryset.filter(total_hours_spent__gt=F('estimated_hours'))
        return queryset

    class Meta:
        model = Task
        fields = [
            'key',
            'name',
            'job_no',
            'position_no',
            'image_no',
            'created_by',
            'created_by_username',
            'completed_by',
            'completion_date',
            'completion_date__gte',
            'completion_date__lte',
            'finish_time',
            'finish_time__gte',
            'finish_time__lte',
            'machine_fk',
            'machine_fk__isnull',
            'has_timer',
            'in_plan',
            'exceeded_estimated_hours',
        ]
