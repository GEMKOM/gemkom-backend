from django.urls import path
from .views import (
    snapshot,
    operations_report,
    subcontracting_report,
    procurement_report,
    sales_report,
    job_orders_report,
)

urlpatterns = [
    path('snapshot/', snapshot, name='reports-snapshot'),
    path('overview/operations/', operations_report, name='reports-overview-operations'),
    path('overview/subcontracting/', subcontracting_report, name='reports-overview-subcontracting'),
    path('overview/procurement/', procurement_report, name='reports-overview-procurement'),
    path('overview/sales/', sales_report, name='reports-overview-sales'),
    path('overview/job-orders/', job_orders_report, name='reports-overview-job-orders'),
]
