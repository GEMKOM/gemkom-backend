from django.urls import path

from .views import (
    PositionDetailView,
    PositionHoldersView,
    PositionListCreateView,
    PositionPermissionsView,
    PositionTreeView,
    UserGroupDetailView,
    UserGroupListCreateView,
    UserGroupPositionsView,
)

urlpatterns = [
    path('positions/', PositionListCreateView.as_view(), name='position-list'),
    path('positions/tree/', PositionTreeView.as_view(), name='position-tree'),
    path('positions/<int:pk>/', PositionDetailView.as_view(), name='position-detail'),
    path('positions/<int:pk>/permissions/', PositionPermissionsView.as_view(), name='position-permissions'),
    path('positions/<int:pk>/holders/', PositionHoldersView.as_view(), name='position-holders'),

    path('groups/', UserGroupListCreateView.as_view(), name='usergroup-list'),
    path('groups/<int:pk>/', UserGroupDetailView.as_view(), name='usergroup-detail'),
    path('groups/<int:pk>/positions/', UserGroupPositionsView.as_view(), name='usergroup-positions'),
]
