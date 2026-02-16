import django_filters
from django.db import models
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

    # Filter by planning request number
    planning_request_number = django_filters.CharFilter(
        field_name='planning_request__request_number',
        lookup_expr='icontains',
        label='Planning Request Number'
    )

    # Filter items available for procurement (ready status + needs purchase + not in active PR)
    available_for_procurement = django_filters.BooleanFilter(
        method='filter_available_for_procurement',
        label='Available for Procurement'
    )

    item_type = django_filters.CharFilter(
        field_name='item__item_type',
        lookup_expr='exact',
        label='Item Type'
    )

    item_type_exclude = django_filters.CharFilter(
        field_name='item__item_type',
        exclude=True,
        label='Exclude Item Type'
    )

    class Meta:
        model = PlanningRequestItem
        fields = {
            'planning_request': ['exact'],
            'item': ['exact'],
            'job_no': ['exact', 'icontains'],
            'priority': ['exact'],
            'is_delivered': ['exact'],
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
        Filter items by availability status (supports partial conversion).
        - is_available=true: Items with remaining quantity for purchase
        - is_available=false: Items fully converted (no remaining quantity)
        """
        from django.db.models import Q, Sum, OuterRef, Subquery, Value
        from django.db.models.functions import Coalesce
        from decimal import Decimal
        from procurement.models import PurchaseRequestItem

        # Subquery to calculate quantity already in active PRs
        quantity_in_active_prs = PurchaseRequestItem.objects.filter(
            planning_request_item=OuterRef('pk')
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('planning_request_item').annotate(
            total=Sum('quantity')
        ).values('total')

        # Annotate with remaining quantity
        queryset = queryset.annotate(
            _qty_in_prs=Coalesce(Subquery(quantity_in_active_prs), Value(Decimal('0.00'))),
        )

        if value:  # is_available=true - has remaining quantity
            return queryset.filter(quantity_to_purchase__gt=models.F('_qty_in_prs'))
        else:  # is_available=false - fully converted
            return queryset.filter(quantity_to_purchase__lte=models.F('_qty_in_prs'))

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
        Filter items available for procurement to select (supports partial conversion).

        An item is available for procurement if:
        1. Planning request status is 'ready' or 'converted'
        2. Item has quantity_to_purchase > 0
        3. Item has remaining quantity (quantity_to_purchase > quantity_in_active_prs)

        Note: 'converted' status is included so that when a PR is rejected, items become available again.
        With partial conversion, items can be partially in PRs but still have remaining quantity available.

        This is the main filter procurement should use!
        """
        if not value:
            return queryset

        from django.db.models import Q, Sum, OuterRef, Subquery, Value
        from django.db.models.functions import Coalesce, Greatest
        from decimal import Decimal
        from procurement.models import PurchaseRequestItem

        # FK path: PurchaseRequestItems directly linked via planning_request_item FK
        qty_via_fk = PurchaseRequestItem.objects.filter(
            planning_request_item=OuterRef('pk')
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('planning_request_item').annotate(
            total=Sum('quantity')
        ).values('total')

        # M2M path: PurchaseRequestItems in PRs linked via M2M, matching by item_id.
        # This covers historical data where FK was not set.
        # May overcount when multiple planning items share the same item_id in one PR,
        # but overcounting is safe (prevents items from falsely showing as available).
        qty_via_m2m = PurchaseRequestItem.objects.filter(
            purchase_request__planning_request_items=OuterRef('pk'),
            item_id=OuterRef('item_id'),
        ).exclude(
            Q(purchase_request__status='rejected') |
            Q(purchase_request__status='cancelled')
        ).values('item_id').annotate(
            total=Sum('quantity')
        ).values('total')

        zero = Value(Decimal('0.00'))

        # Use the greater of FK and M2M totals — FK is authoritative when set,
        # M2M is fallback for historical data
        queryset = queryset.annotate(
            _qty_in_prs=Greatest(
                Coalesce(Subquery(qty_via_fk), zero),
                Coalesce(Subquery(qty_via_m2m), zero),
            ),
        )

        return queryset.filter(
            Q(planning_request__status='ready') | Q(planning_request__status='converted'),  # Ready or converted
            quantity_to_purchase__gt=models.F('_qty_in_prs')  # Has remaining quantity available (also implies > 0)
        )


class PlanningRequestFilter(django_filters.FilterSet):
    """
    Filter for PlanningRequest with focus on procurement needs.
    """
    # Filter by request number (case-insensitive partial match)
    request_number = django_filters.CharFilter(
        field_name='request_number',
        lookup_expr='icontains',
        label='Request Number'
    )

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
        1. Status is 'ready' or 'converted' (converted means some items are in PRs but not all approved yet)
        2. Has at least one item with quantity_to_purchase > 0
        """
        if not value:
            return queryset

        from django.db.models import Q, Exists, OuterRef
        from decimal import Decimal

        # Subquery to check if planning request has items that need purchasing
        has_items_to_purchase = PlanningRequestItem.objects.filter(
            planning_request=OuterRef('pk'),
            quantity_to_purchase__gt=Decimal('0')
        )

        return queryset.filter(
            Q(status='ready') | Q(status='converted')  # Ready or converted status
        ).filter(
            Exists(has_items_to_purchase)
        )
