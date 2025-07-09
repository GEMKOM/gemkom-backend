    
from django.urls import path

from machines.views import MachineDetailView, MachineFaultDetailView, MachineFaultListCreateView, MachineListCreateView, MachineTypeChoicesView


urlpatterns = [
    path("", MachineListCreateView.as_view(), name="machine-list"),
    path('<int:pk>/', MachineDetailView.as_view(), name='machine-detail'),
    path('types/', MachineTypeChoicesView.as_view(), name='machine-types'),
    path('faults/', MachineFaultListCreateView.as_view(), name='machinefault-list-create'),
    path('faults/<int:pk>/', MachineFaultDetailView.as_view(), name='machinefault-detail'),
]
