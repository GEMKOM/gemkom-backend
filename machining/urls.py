from django.urls import path

from machining.queue_views import DrainCostQueueView
from .views import HoldTaskViewSet, InitTaskKeyCounterView, JobCostSnapshotView, JobHoursReportView, MachineTimelineView, PlanningAggregateView, PlanningBulkSaveView, PlanningListView, ProductionPlanView, TaskBulkCreateView, TimerDetailView, TimerReportView, TimerStartView, TimerStopView, TimerManualEntryView, TimerListView, UnmarkTaskCompletedView
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, MarkTaskCompletedView

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'hold-tasks', HoldTaskViewSet, basename='hold-task')


urlpatterns = [
    path("timers/start/", TimerStartView.as_view()),
    path("timers/stop/", TimerStopView.as_view()),
    path("manual-time/", TimerManualEntryView.as_view()),
    path("timers/", TimerListView.as_view()),
    path("timer-report/", TimerReportView.as_view()),
    path('timers/<int:pk>/', TimerDetailView.as_view(), name='timer-detail'),
    path('tasks/mark-completed/', MarkTaskCompletedView.as_view(), name='mark-task-completed'),
    path('tasks/unmark-completed/', UnmarkTaskCompletedView.as_view(), name='mark-task-completed'),
    path('tasks/bulk-create/', TaskBulkCreateView.as_view(), name='task-bulk-create'),
    path('tasks/init-counter/', InitTaskKeyCounterView.as_view(), name='init-task-key-counter'),
    path('planning/list/', PlanningListView.as_view(), name='planning-list'),
    path('planning/bulk-save/', PlanningBulkSaveView.as_view(), name='planning-bulk-save'),
    path("planning/overview/", PlanningAggregateView.as_view(), name="planning-window"),
    path('analytics/machine-timeline/', MachineTimelineView.as_view(), name='analytics-machine-timeline'),
    path("reports/job-hours/", JobHoursReportView.as_view(), name="job-hours-report"),
    path("reports/job-costs/<str:job_no>/", JobCostSnapshotView.as_view()),
    path('reports/production-plan/', ProductionPlanView.as_view(), name='production-plan'),

]

queue_urlpatterns = [
    path("internal/drain-job-cost-queue/", DrainCostQueueView.as_view()),
]

urlpatterns += router.urls
urlpatterns += queue_urlpatterns
