import django_filters
from .models import Machine

class MachineFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    machine_type = django_filters.CharFilter(field_name="machine_type", lookup_expr="exact")
    used_in = django_filters.CharFilter(field_name="used_in", lookup_expr="exact")
    is_active = django_filters.BooleanFilter(field_name="is_active")

    class Meta:
        model = Machine
        fields = ["name", "machine_type", "used_in", "is_active"]