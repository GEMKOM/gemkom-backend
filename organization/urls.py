from django.urls import path

from .views import (
    PositionDetailView,
    PositionHoldersView,
    PositionListCreateView,
    PositionPermissionsView,
    PositionTreeView,
)

urlpatterns = [
    path('positions/', PositionListCreateView.as_view(), name='position-list'),
    path('positions/tree/', PositionTreeView.as_view(), name='position-tree'),
    path('positions/<int:pk>/', PositionDetailView.as_view(), name='position-detail'),
    path('positions/<int:pk>/permissions/', PositionPermissionsView.as_view(), name='position-permissions'),
    path('positions/<int:pk>/holders/', PositionHoldersView.as_view(), name='position-holders'),
]
