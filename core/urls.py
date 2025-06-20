from django.urls import path
from .views import DBTestView
from users.views import LoginView

urlpatterns = [
    path('login/', LoginView.as_view()),
    path("db-test/", DBTestView.as_view()),

]