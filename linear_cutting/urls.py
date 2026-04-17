from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LinearCuttingSessionViewSet,
    LinearCuttingPartViewSet,
    LinearCuttingTaskViewSet,
    OptimizeView,
    ConfirmView,
    CuttingListPDFView,
    TaskPDFView,
    TimerStartView,
    TimerStopView,
    TimerManualEntryView,
    TimerListView,
    TimerDetailView,
    MarkTaskCompletedView,
    UnmarkTaskCompletedView,
)

app_name = 'linear_cutting'

router = DefaultRouter()
router.register(r'sessions', LinearCuttingSessionViewSet, basename='session')
router.register(r'parts', LinearCuttingPartViewSet, basename='part')
router.register(r'tasks', LinearCuttingTaskViewSet, basename='task')

urlpatterns = [
    # Session actions
    path('sessions/<str:key>/optimize/', OptimizeView.as_view(), name='session-optimize'),
    path('sessions/<str:key>/confirm/', ConfirmView.as_view(), name='session-confirm'),
    path('sessions/<str:key>/pdf/', CuttingListPDFView.as_view(), name='session-pdf'),

    # Task actions
    path('tasks/<str:key>/pdf/', TaskPDFView.as_view(), name='task-pdf'),
    path('tasks/mark-completed/', MarkTaskCompletedView.as_view(), name='mark-task-completed'),
    path('tasks/unmark-completed/', UnmarkTaskCompletedView.as_view(), name='unmark-task-completed'),

    # Timer URLs
    path('timers/start/', TimerStartView.as_view(), name='timer-start'),
    path('timers/stop/', TimerStopView.as_view(), name='timer-stop'),
    path('timers/manual/', TimerManualEntryView.as_view(), name='manual-time'),
    path('timers/', TimerListView.as_view(), name='timer-list'),
    path('timers/<int:pk>/', TimerDetailView.as_view(), name='timer-detail'),
]

urlpatterns += router.urls
