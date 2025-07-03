from django.urls import path
from .views import TimerReportView, TimerStartView, TimerStopView, TimerManualEntryView, TimerListView

urlpatterns = [
    path("timers/start/", TimerStartView.as_view()),
    path("timers/stop/", TimerStopView.as_view()),
    path("manual-time/", TimerManualEntryView.as_view()),
    path("timers/", TimerListView.as_view()),
    path("timer-report/", TimerReportView.as_view())

]
