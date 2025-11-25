import django_filters
from .models import PlanningRequestItem, PlanningRequest


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

    # Filter items that need to be purchased (quantity_to_purchase > 0)
    needs_purchase = django_filters.BooleanFilter(
        method='filter_needs_purchase',
        label='Needs Purchase (quantity_to_purchase > 0)'
    )

    # Filter by planning request status
    planning_request_status = django_filters.CharFilter(
        field_name='planning_request__status',
        lookup_expr='exact',
        label='Planning Request Status'
    )

    # Filter items available for procurement (ready status + needs purchase + not in active PR)
    available_for_procurement = django_filters.BooleanFilter(
        method='filter_available_for_procurement',
        label='Available for Procurement'
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

    def filter_needs_purchase(self, queryset, name, value):
        """
        Filter items that need to be purchased.
        - needs_purchase=true: Only items with quantity_to_purchase > 0
        - needs_purchase=false: Only items with quantity_to_purchase = 0 (fully from inventory)
        """
        from decimal import Decimal

        if value:  # needs_purchase=true
            return queryset.filter(quantity_to_purchase__gt=Decimal('0'))
        else:  # needs_purchase=false
            return queryset.filter(quantity_to_purchase=Decimal('0'))

    def filter_available_for_procurement(self, queryset, name, value):
        """
        Filter items available for procurement to select.

        An item is available for procurement if:
        1. Planning request status is 'ready'
        2. Item has quantity_to_purchase > 0
        3. Item is not already in an active purchase request

        This is the main filter procurement should use!
        """
        if not value:
            return queryset

        from django.db.models import Q, Exists, OuterRef
        from decimal import Decimal
        from procurement.models import PurchaseRequest

        # Subquery to check if item is in any active purchase request
        active_pr_exists = PurchaseRequest.objects.filter(
            planning_request_items=OuterRef('pk')
        ).exclude(
            Q(status='rejected') | Q(status='cancelled')
        )

        return queryset.filter(
            planning_request__status='ready',  # Planning request must be ready
            quantity_to_purchase__gt=Decimal('0')  # Must need purchasing
        ).exclude(
            Exists(active_pr_exists)  # Not already in active purchase request
        )


class PlanningRequestFilter(django_filters.FilterSet):
    """
    Filter for PlanningRequest with focus on procurement needs.
    """
    # Filter by status
    status = django_filters.CharFilter(
        field_name='status',
        lookup_expr='exact',
        label='Status'
    )

    # Filter by inventory control flags
    check_inventory = django_filters.BooleanFilter(
        field_name='check_inventory',
        label='Has Inventory Control'
    )

    inventory_control_completed = django_filters.BooleanFilter(
        field_name='inventory_control_completed',
        label='Inventory Control Completed'
    )

    fully_from_inventory = django_filters.BooleanFilter(
        field_name='fully_from_inventory',
        label='Fully From Inventory'
    )

    # Filter requests available for procurement
    available_for_procurement = django_filters.BooleanFilter(
        method='filter_available_for_procurement',
        label='Available for Procurement (status=ready with items to purchase)'
    )

    class Meta:
        model = PlanningRequest
        fields = {
            'status': ['exact'],
            'priority': ['exact'],
            'created_by': ['exact'],
            'department_request': ['exact'],
        }

    def filter_available_for_procurement(self, queryset, name, value):
        """
        Filter planning requests available for procurement.

        A planning request is available if:
        1. Status is 'ready'
        2. Has at least one item with quantity_to_purchase > 0
        """
        if not value:
            return queryset

        from django.db.models import Exists, OuterRef
        from decimal import Decimal

        # Subquery to check if planning request has items that need purchasing
        has_items_to_purchase = PlanningRequestItem.objects.filter(
            planning_request=OuterRef('pk'),
            quantity_to_purchase__gt=Decimal('0')
        )

        return queryset.filter(
            status='ready'
        ).filter(
            Exists(has_items_to_purchase)
        )
