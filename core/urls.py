from django.urls import path
from . import views

urlpatterns = [
    path("db-test/", views.db_test),
]
