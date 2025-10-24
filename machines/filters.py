import django_filters
from .models import Machine, MachineFault

class CharInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass

class MachineFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    code = django_filters.CharFilter(field_name="name", lookup_expr="icontains")
    assigned_users = django_filters.BaseInFilter(field_name='assigned_users', lookup_expr='in')
    machine_type = django_filters.CharFilter(field_name="machine_type", lookup_expr="exact")
    used_in = django_filters.CharFilter(field_name="used_in", lookup_expr="exact")
    is_active = django_filters.BooleanFilter(field_name="is_active")
    exclude_used_in = CharInFilter(method="filter_exclude_used_in")

    class Meta:
        model = Machine
        fields = ["name", "code", "assigned_users", "machine_type", "used_in", "is_active", "exclude_used_in"]

    def filter_exclude_used_in(self, queryset, name, value):
        # value is a list when comma-separated values are provided
        return queryset.exclude(used_in__in=value if isinstance(value, list) else [value])

class MachineFaultFilter(django_filters.FilterSet):
    # Convenience filters
    unresolved = django_filters.BooleanFilter(method='filter_unresolved')
    unassigned_machine = django_filters.BooleanFilter(field_name='machine', lookup_expr='isnull')
    area = django_filters.CharFilter(field_name='area', lookup_expr='iexact')
    machine_id = django_filters.NumberFilter(field_name='machine__id')  # Backwards-compat with your query param

    def filter_unresolved(self, qs, name, value):
        return qs.filter(resolved_at__isnull=True) if value else qs

    class Meta:
        model = MachineFault
        fields = [
            # native fields / relations
            'machine', 'reported_by',
            # booleans
            'is_breaking', 'is_maintenance',
            # convenience
            'unassigned_machine', 'unresolved', 'area', 'machine_id',
        ]