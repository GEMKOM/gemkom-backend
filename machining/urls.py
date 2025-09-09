from django.urls import path
from .views import HoldTaskViewSet, InitTaskKeyCounterView, MachinePlanView, MachineTimelineView, PlanningBulkSaveView, PlanningCandidatesView, TaskBulkCreateView, TimerDetailView, TimerReportView, TimerStartView, TimerStopView, TimerManualEntryView, TimerListView, UnmarkTaskCompletedView
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
    path('planning/machine-plan/', MachinePlanView.as_view(), name='planning-machine-plan'),
    path('planning/bulk-save/', PlanningBulkSaveView.as_view(), name='planning-bulk-save'),
    path('analytics/machine-timeline/', MachineTimelineView.as_view(), name='analytics-machine-timeline'),
    path('planning/candidates/', PlanningCandidatesView.as_view(), name='planning-candidates'),

]

urlpatterns += router.urls
