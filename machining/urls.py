from django.urls import path
from .views import TimerDetailView, TimerReportView, TimerStartView, TimerStopView, TimerManualEntryView, TimerListView, UnmarkTaskCompletedView
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, MarkTaskCompletedView

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')


urlpatterns = [
    path("timers/start/", TimerStartView.as_view()),
    path("timers/stop/", TimerStopView.as_view()),
    path("manual-time/", TimerManualEntryView.as_view()),
    path("timers/", TimerListView.as_view()),
    path("timer-report/", TimerReportView.as_view()),
    path('timers/<int:pk>/', TimerDetailView.as_view(), name='timer-detail'),
    path('tasks/mark-completed/', MarkTaskCompletedView.as_view(), name='mark-task-completed'),
    path('tasks/unmark-completed/', UnmarkTaskCompletedView.as_view(), name='mark-task-completed'),

]

urlpatterns += router.urls
