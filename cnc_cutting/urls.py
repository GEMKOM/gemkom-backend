from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CncTaskViewSet, CncPartViewSet, CncTaskFileViewSet

app_name = 'cnc_cutting'

router = DefaultRouter()
router.register(r'tasks', CncTaskViewSet, basename='cnctask')
router.register(r'parts', CncPartViewSet, basename='cncpart')
router.register(r'files', CncTaskFileViewSet, basename='cnctaskfile')

urlpatterns = [
    path('', include(router.urls)),
]