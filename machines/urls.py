    
from django.urls import path

from machines.views import MachineCreateView, MachineListView, MachineUpdateView

urlpatterns = [
    path("", MachineListView.as_view(), name="machine-list"),
    path('create/', MachineCreateView.as_view(), name='machine-create'),
    path('<int:pk>/edit/', MachineUpdateView.as_view(), name='machine-edit'),
]
