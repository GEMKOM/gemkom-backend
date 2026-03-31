from django.urls import path
from .views import overview, snapshot

urlpatterns = [
    path('overview/', overview, name='reports-overview'),
    path('snapshot/', snapshot, name='reports-snapshot'),
]
