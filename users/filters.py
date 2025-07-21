from django_filters import rest_framework as filters
from django.contrib.auth.models import User

class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass

class UserFilter(filters.FilterSet):
    team = CharInFilter(field_name='profile__team', lookup_expr='in')
    is_admin = filters.BooleanFilter(field_name='profile__is_admin')
    is_lead = filters.BooleanFilter(field_name='profile__is_lead')
    must_reset_password = filters.BooleanFilter(field_name='profile__must_reset_password')

    class Meta:
        model = User
        fields = ['team', 'is_admin', 'is_lead', 'must_reset_password']
