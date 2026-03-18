    
from django.urls import path

from machines.reports.machine_faults_report import MachineFaultsSummaryReportView
from machines.reports.user_resolution_report import UserResolutionReportView
from machines.views import (
    FaultTimerDetailView, FaultTimerListView, FaultTimerStartView, FaultTimerStopView,
    MachineCalendarView, MachineDetailView, MachineDropdownView,
    MachineFaultCompleteView, MachineFaultDetailView, MachineFaultListCreateView,
    MachineListCreateView, MachineTypeChoicesView, UsedInChoicesView,
)


urlpatterns = [
    path("", MachineListCreateView.as_view(), name="machine-list"),
    path('dropdown/', MachineDropdownView.as_view(), name='machine-dropdown'),
    path('<int:pk>/', MachineDetailView.as_view(), name='machine-detail'),
    path('types/', MachineTypeChoicesView.as_view(), name='machine-types'),
    path('used_in/', UsedInChoicesView.as_view(), name='used-in-choices'),
    path('faults/', MachineFaultListCreateView.as_view(), name='machinefault-list-create'),
    path('faults/<int:pk>/', MachineFaultDetailView.as_view(), name='machinefault-detail'),
    path('faults/<int:pk>/complete/', MachineFaultCompleteView.as_view(), name='machinefault-complete'),
    path('faults/timers/start/', FaultTimerStartView.as_view(), name='fault-timer-start'),
    path('faults/timers/stop/', FaultTimerStopView.as_view(), name='fault-timer-stop'),
    path('faults/timers/', FaultTimerListView.as_view(), name='fault-timer-list'),
    path('faults/timers/<int:pk>/', FaultTimerDetailView.as_view(), name='fault-timer-detail'),
    path('calendar/', MachineCalendarView.as_view(), name='planning-calendar'),
    path('reports/faults/', MachineFaultsSummaryReportView.as_view(), name='machine-faults-report'),
    path('reports/user-resolution/', UserResolutionReportView.as_view(), name='user-resolution-report'),
]
