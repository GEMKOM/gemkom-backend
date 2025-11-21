import django_filters
from .models import PlanningRequestItem


class PlanningRequestItemFilter(django_filters.FilterSet):
    """
    Advanced filter for PlanningRequestItem with search capabilities for item code and name.
    """
    # Search by item code (case-insensitive partial match)
    item_code = django_filters.CharFilter(
        field_name='item__code',
        lookup_expr='icontains',
        label='Item Code'
    )

    # Search by item name (case-insensitive partial match)
    item_name = django_filters.CharFilter(
        field_name='item__name',
        lookup_expr='icontains',
        label='Item Name'
    )

    # Combined search across both item code and name
    search = django_filters.CharFilter(
        method='filter_search',
        label='Search (code or name)'
    )

    class Meta:
        model = PlanningRequestItem
        fields = {
            'planning_request': ['exact'],
            'item': ['exact'],
            'job_no': ['exact', 'icontains'],
            'priority': ['exact'],
        }

    def filter_search(self, queryset, name, value):
        """
        Filter by searching across both item code and item name.
        Returns items where either the code or name contains the search term.
        """
        if not value:
            return queryset

        from django.db.models import Q
        return queryset.filter(
            Q(item__code__icontains=value) | Q(item__name__icontains=value)
        )
