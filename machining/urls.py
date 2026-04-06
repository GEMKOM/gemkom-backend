from django.urls import path
from .views import (
    DailyEfficiencyReportView,
    UserReportView,
    UserTaskDetailView,
    JobHoursReportView,
    MachineTimelineView,
    MachiningJobEntriesReportView,
    PlanningAggregateView,
    TimerDetailView,
    TimerListView,
    TimerManualEntryView,
    TimerReportView,
    TimerStartView,
    TimerStopView,
)

# Note: Task-specific views removed. Use /tasks/operations/ endpoints instead.

urlpatterns = [
    # Timer endpoints (work with Operations via generic foreign key)
    path("timers/start/", TimerStartView.as_view()),
    path("timers/stop/", TimerStopView.as_view()),
    path("manual-time/", TimerManualEntryView.as_view()),
    path("timers/", TimerListView.as_view()),
    path("timer-report/", TimerReportView.as_view()),
    path('timers/<int:pk>/', TimerDetailView.as_view(), name='timer-detail'),

    # Planning & Analytics (now using Operation/Part)
    path("planning/overview/", PlanningAggregateView.as_view(), name="planning-window"),
    path('analytics/machine-timeline/', MachineTimelineView.as_view(), name='analytics-machine-timeline'),

    # Reports (now using Operation/Part)
    path("reports/job-hours/", JobHoursReportView.as_view(), name="job-hours-report"),
    path('reports/job-entries/', MachiningJobEntriesReportView.as_view(), name='machining-job-entries-report'),
    path('reports/user-report/', UserReportView.as_view(), name='user-report'),
    path('reports/user-task-detail/', UserTaskDetailView.as_view(), name='user-task-detail'),
    path('reports/daily-efficiency/', DailyEfficiencyReportView.as_view(), name='daily-efficiency-report'),
]
