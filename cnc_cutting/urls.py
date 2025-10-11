from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CncTaskViewSet

app_name = 'cnc_cutting'

router = DefaultRouter()
router.register(r'tasks', CncTaskViewSet, basename='cnctask')

urlpatterns = [
    path('', include(router.urls)),
]