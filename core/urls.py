from django.urls import path
from .views import DBTestView, TimerNowView
from users.views import LoginView

urlpatterns = [
    path('login/', LoginView.as_view()),
    path("db-test/", DBTestView.as_view()),
    path("now/", TimerNowView.as_view()),
]