from django.urls import path
from .views import CustomTokenObtainPairView, DBTestView, LatestCurrencyRatesView, TimerNowView, CombinedJobCostListView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("db-test/", DBTestView.as_view()),
    path("now/", TimerNowView.as_view()),
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path('currency-rates/', LatestCurrencyRatesView.as_view(), name="currency-rates"),
    path('reports/combined-job-costs/', CombinedJobCostListView.as_view(), name="combined-job-costs"),
]