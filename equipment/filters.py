import django_filters

from .models import EquipmentItem, EquipmentCheckout


class EquipmentItemFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(lookup_expr='icontains')
    asset_type = django_filters.CharFilter(lookup_expr='exact')
    is_active = django_filters.BooleanFilter()
    code = django_filters.CharFilter(lookup_expr='icontains')
    name = django_filters.CharFilter(lookup_expr='icontains')

    class Meta:
        model = EquipmentItem
        fields = ['category', 'asset_type', 'is_active', 'code', 'name']


class EquipmentCheckoutFilter(django_filters.FilterSet):
    item = django_filters.NumberFilter(field_name='item_id')
    checked_out_by = django_filters.NumberFilter(field_name='checked_out_by_id')
    job_order = django_filters.CharFilter(field_name='job_order_id', lookup_expr='exact')
    is_returned = django_filters.BooleanFilter(method='filter_is_returned')
    checked_out_at__gte = django_filters.DateTimeFilter(field_name='checked_out_at', lookup_expr='gte')
    checked_out_at__lte = django_filters.DateTimeFilter(field_name='checked_out_at', lookup_expr='lte')

    class Meta:
        model = EquipmentCheckout
        fields = ['item', 'checked_out_by', 'job_order', 'is_returned']

    def filter_is_returned(self, queryset, name, value):
        if value:
            return queryset.filter(checked_in_at__isnull=False)
        return queryset.filter(checked_in_at__isnull=True)
