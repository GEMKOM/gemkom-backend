from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    WeldingTimeEntryViewSet,
    WeldingTimeEntryBulkCreateView,
    WeldingJobCostListView,
    WeldingJobEntriesReportView,
    UserWorkHoursReportView,
)
from .queue_views import DrainWeldingCostQueueView

router = DefaultRouter()
router.register(r'time-entries', WeldingTimeEntryViewSet, basename='welding-time-entry')

urlpatterns = [
    path('time-entries/bulk-create/', WeldingTimeEntryBulkCreateView.as_view(), name='welding-bulk-create'),
    path('reports/job-costs/', WeldingJobCostListView.as_view(), name='welding-job-cost-list'),
    path('reports/job-entries/', WeldingJobEntriesReportView.as_view(), name='welding-job-entries-report'),
    path('reports/user-work-hours/', UserWorkHoursReportView.as_view(), name='welding-user-work-hours'),
]

queue_urlpatterns = [
    path("internal/drain-job-cost-queue/", DrainWeldingCostQueueView.as_view()),
]

urlpatterns += router.urls
urlpatterns += queue_urlpatterns
