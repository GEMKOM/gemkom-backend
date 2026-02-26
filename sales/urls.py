from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import OfferTemplateViewSet, SalesOfferViewSet

router = DefaultRouter()
router.register(r'offers', SalesOfferViewSet, basename='salesoffer')
router.register(r'offer-templates', OfferTemplateViewSet, basename='offertemplate')

urlpatterns = [
    path('', include(router.urls)),
]
