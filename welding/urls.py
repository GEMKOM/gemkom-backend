from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import WeldingTimeEntryViewSet, WeldingTimeEntryBulkCreateView

router = DefaultRouter()
router.register(r'time-entries', WeldingTimeEntryViewSet, basename='welding-time-entry')

urlpatterns = [
    path('time-entries/bulk-create/', WeldingTimeEntryBulkCreateView.as_view(), name='welding-bulk-create'),
]

urlpatterns += router.urls
