import django_filters
from .models import Operation


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
