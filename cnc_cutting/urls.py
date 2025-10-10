from django.urls import path
from .views import CncTaskListCreateView, CncTaskDetailView

app_name = 'cnc_cutting'

urlpatterns = [
    path('', CncTaskListCreateView.as_view(), name='cnctask-list-create'),
    path('<int:pk>/', CncTaskDetailView.as_view(), name='cnctask-detail'),
]