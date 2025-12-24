from django.contrib.auth.models import User
from django_filters import rest_framework as filters
from django_filters.filters import BaseInFilter, CharFilter
from rest_framework.filters import OrderingFilter

class CharInFilter(BaseInFilter, CharFilter):
    """Accepts comma-separated values, e.g. ?team=machining,design"""
    pass

class UserFilter(filters.FilterSet):
    # substring match anywhere in username (on, onat, nat, cali…)
    username = filters.CharFilter(field_name='username', lookup_expr='icontains')

    # allow single or multi select via comma-separated values
    team = CharInFilter(field_name='profile__team', lookup_expr='in')
    work_location = CharInFilter(field_name='profile__work_location', lookup_expr='in')
    occupation = CharInFilter(field_name='profile__occupation', lookup_expr='in')

    reset_password_request = filters.BooleanFilter(
        field_name='profile__reset_password_request'  # or 'reset_password_request' if on User
    )

    is_active = filters.BooleanFilter(field_name='is_active')

    class Meta:
        model = User
        fields = ['username', 'team', 'work_location', 'occupation', 'reset_password_request', 'is_active']


class WageOrderingFilter(OrderingFilter):
    """
    Dynamic ordering fields based on ?mode=overview|records
    """
    ordering_param = "ordering"

    # DRF calls this with (queryset, view, context=None)
    def get_valid_fields(self, queryset, view, context=None):
        request = getattr(view, "request", None)
        mode = ((request.query_params.get("mode") if request else None) or "overview").lower()

        if mode == "records":
            # WageRate fields + related user fields
            return [
                ("effective_from", "effective_from"),
                ("currency", "currency"),
                ("base_monthly", "base_monthly"),
                ("after_hours_multiplier", "after_hours_multiplier"),
                ("sunday_multiplier", "sunday_multiplier"),
                ("created_at", "created_at"),
                ("updated_at", "updated_at"),
                ("user__username", "user__username"),
                ("user__first_name", "user__first_name"),
                ("user__last_name", "user__last_name"),
            ]

        # overview (User + annotations)
        return [
            ("id", "id"),
            ("username", "username"),
            ("first_name", "first_name"),
            ("last_name", "last_name"),
            ("team", "profile__team"),
            ("occupation", "profile__occupation"),
            ("work_location", "profile__work_location"),
            ("has_wage", "has_wage"),
            ("current_effective_from", "current_effective_from"),
            ("current_currency", "current_currency"),
            ("current_base_monthly", "current_base_monthly"),
            ("current_after_hours_multiplier", "current_after_hours_multiplier"),
            ("current_sunday_multiplier", "current_sunday_multiplier"),
        ]

    def get_default_ordering(self, view):
        request = getattr(view, "request", None)
        mode = ((request.query_params.get("mode") if request else None) or "overview").lower()
        if mode == "records":
            return ["-effective_from", "user__username"]
        return ["username"]