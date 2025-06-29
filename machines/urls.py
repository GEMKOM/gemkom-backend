    
from django.urls import path

from machines.views import MachineCreateView, MachineFaultDetailView, MachineFaultListCreateView, MachineListView, MachineUpdateView

urlpatterns = [
    path("", MachineListView.as_view(), name="machine-list"),
    path('create/', MachineCreateView.as_view(), name='machine-create'),
    path('<int:pk>/edit/', MachineUpdateView.as_view(), name='machine-edit'),
    path('faults/', MachineFaultListCreateView.as_view(), name='machinefault-list-create'),
    path('faults/<int:pk>/', MachineFaultDetailView.as_view(), name='machinefault-detail'),
]
