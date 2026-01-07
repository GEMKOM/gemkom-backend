import django_filters
from .models import Operation, Part


class PartFilter(django_filters.FilterSet):
    """
    Filter for Part model.
    Supports all the same filters as the old machining TaskFilter.
    """
    # Text search filters
    key = django_filters.CharFilter(lookup_expr='exact')
    task_key = django_filters.CharFilter(lookup_expr='exact')
    name = django_filters.CharFilter(lookup_expr='icontains')
    job_no = django_filters.CharFilter(lookup_expr='icontains')
    position_no = django_filters.CharFilter(lookup_expr='icontains')
    image_no = django_filters.CharFilter(lookup_expr='icontains')
    created_by_username = django_filters.CharFilter(field_name='created_by__username', lookup_expr='icontains')

    # Boolean filters
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')
    has_operations = django_filters.BooleanFilter(method='filter_has_operations')
    has_unassigned_operations = django_filters.BooleanFilter(method='filter_has_unassigned_operations')
    has_unplanned_operations = django_filters.BooleanFilter(method='filter_has_unplanned_operations')

    # Date filters
    completion_date = django_filters.DateFilter(field_name='completion_date')
    completion_date__gte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='gte')
    completion_date__lte = django_filters.NumberFilter(field_name='completion_date', lookup_expr='lte')

    finish_time = django_filters.DateFilter(field_name='finish_time')
    finish_time__gte = django_filters.DateFilter(field_name='finish_time', lookup_expr='gte')
    finish_time__lte = django_filters.DateFilter(field_name='finish_time', lookup_expr='lte')

    class Meta:
        model = Part
        fields = [
            'key',
            'task_key',
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
            'completion_date__isnull',
            'finish_time',
            'finish_time__gte',
            'finish_time__lte',
            'has_operations',
            'has_unassigned_operations',
            'has_unplanned_operations',
        ]

    def filter_has_operations(self, queryset, name, value):
        """
        Filter parts based on whether they have operations.
        - value=True: parts with at least one operation
        - value=False: parts with no operations
        """
        if value:
            # Has operations
            return queryset.filter(operations__isnull=False).distinct()
        else:
            # No operations
            return queryset.filter(operations__isnull=True)

    def filter_has_unassigned_operations(self, queryset, name, value):
        """
        Filter parts based on whether they have incomplete operations without a machine.
        - value=True: parts with at least one incomplete operation missing machine assignment
        - value=False: parts where all incomplete operations have machines assigned
        """
        from django.db.models import Q

        if value:
            # Has incomplete operations without machine
            return queryset.filter(
                Q(operations__completion_date__isnull=True) &
                Q(operations__machine_fk__isnull=True)
            ).distinct()
        else:
            # All incomplete operations have machines (or no incomplete operations)
            # Exclude parts that have any incomplete operation without machine
            parts_with_unassigned = queryset.filter(
                Q(operations__completion_date__isnull=True) &
                Q(operations__machine_fk__isnull=True)
            ).values_list('key', flat=True)
            return queryset.exclude(key__in=parts_with_unassigned)

    def filter_has_unplanned_operations(self, queryset, name, value):
        """
        Filter parts based on whether they have incomplete operations not in plan.
        - value=True: parts with at least one incomplete operation not in plan
        - value=False: parts where all incomplete operations are in plan
        """
        from django.db.models import Q

        if value:
            # Has incomplete operations not in plan
            return queryset.filter(
                Q(operations__completion_date__isnull=True) &
                (Q(operations__in_plan=False) | Q(operations__in_plan__isnull=True))
            ).distinct()
        else:
            # All incomplete operations are in plan (or no incomplete operations)
            parts_with_unplanned = queryset.filter(
                Q(operations__completion_date__isnull=True) &
                (Q(operations__in_plan=False) | Q(operations__in_plan__isnull=True))
            ).values_list('key', flat=True)
            return queryset.exclude(key__in=parts_with_unplanned)


class OperationFilter(django_filters.FilterSet):
    """
    Filter for Operation model.
    Supports filtering by:
    - in_plan: boolean
    - completion_date__isnull: boolean (true for incomplete, false for completed)
    - machine_fk: machine ID
    - part__key: part key
    """
    completion_date__isnull = django_filters.BooleanFilter(field_name='completion_date', lookup_expr='isnull')

    class Meta:
        model = Operation
        fields = [
            'in_plan',
            'completion_date__isnull',
            'machine_fk',
            'part__key',
            'interchangeable',
            'plan_locked',
        ]
