from django.contrib.auth.models import User
from django_filters import rest_framework as filters
from django_filters.filters import BaseInFilter, CharFilter

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

    class Meta:
        model = User
        fields = ['username', 'team', 'work_location', 'occupation', 'reset_password_request']
