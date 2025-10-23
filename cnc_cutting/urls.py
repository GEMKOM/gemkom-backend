from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CncTaskViewSet,
    CncPartViewSet,
    CncTaskFileViewSet,
    TimerStartView,
    TimerStopView,
    TimerManualEntryView,
    TimerListView,
    TimerDetailView,
    TimerReportView,
)

app_name = 'cnc_cutting'

router = DefaultRouter()
router.register(r'tasks', CncTaskViewSet, basename='cnctask')
router.register(r'parts', CncPartViewSet, basename='cncpart')
router.register(r'files', CncTaskFileViewSet, basename='cnctaskfile')

urlpatterns = [
    path('', include(router.urls)),
    # Generic Timer URLs for CNC Cutting
    path("timers/start/", TimerStartView.as_view(), name="timer-start"),
    path("timers/stop/", TimerStopView.as_view(), name="timer-stop"),
    path("manual-time/", TimerManualEntryView.as_view(), name="manual-time"),
    path("timers/", TimerListView.as_view(), name="timer-list"),
    path("timer-report/", TimerReportView.as_view(), name="timer-report"),
    path('timers/<int:pk>/', TimerDetailView.as_view(), name='timer-detail'),
]