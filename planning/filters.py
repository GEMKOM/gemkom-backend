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

    # Filter by availability (not in active purchase requests)
    is_available = django_filters.BooleanFilter(
        method='filter_is_available',
        label='Is Available (not in active purchase requests)'
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

    def filter_is_available(self, queryset, name, value):
        """
        Filter items by availability status.
        - is_available=true: Only items NOT in active purchase requests (rejected/cancelled are OK)
        - is_available=false: Only items already in active purchase requests
        """
        from django.db.models import Q, Exists, OuterRef
        from procurement.models import PurchaseRequest

        # Subquery to check if item is in any active purchase request
        active_pr_exists = PurchaseRequest.objects.filter(
            planning_request_items=OuterRef('pk')
        ).exclude(
            Q(status='rejected') | Q(status='cancelled')
        )

        if value:  # is_available=true
            # Exclude items that are in active purchase requests
            return queryset.exclude(Exists(active_pr_exists))
        else:  # is_available=false
            # Only include items that are in active purchase requests
            return queryset.filter(Exists(active_pr_exists))
