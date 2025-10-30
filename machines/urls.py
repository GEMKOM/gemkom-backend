    
from django.urls import path

from machines.reports.machine_faults_report import MachineFaultsSummaryReportView
from machines.reports.user_resolution_report import UserResolutionReportView
from machines.views import MachineCalendarView, MachineDetailView, MachineFaultDetailView, MachineFaultListCreateView, MachineListCreateView, MachineTypeChoicesView, UsedInChoicesView


urlpatterns = [
    path("", MachineListCreateView.as_view(), name="machine-list"),
    path('<int:pk>/', MachineDetailView.as_view(), name='machine-detail'),
    path('types/', MachineTypeChoicesView.as_view(), name='machine-types'),
    path('used_in/', UsedInChoicesView.as_view(), name='used-in-choices'),
    path('faults/', MachineFaultListCreateView.as_view(), name='machinefault-list-create'),
    path('faults/<int:pk>/', MachineFaultDetailView.as_view(), name='machinefault-detail'),
    path('calendar/', MachineCalendarView.as_view(), name='planning-calendar'),
    path('reports/faults/', MachineFaultsSummaryReportView.as_view(), name='machine-faults-report'),
    path('reports/user-resolution/', UserResolutionReportView.as_view(), name='user-resolution-report'),
]
