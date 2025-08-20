from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaymentTypeViewSet, PurchaseOrderViewSet, StatusChoicesView, SupplierViewSet, ItemViewSet,
    PurchaseRequestViewSet, PurchaseRequestItemViewSet,
    SupplierOfferViewSet, ItemOfferViewSet
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'payment-types', PaymentTypeViewSet)
router.register(r'suppliers', SupplierViewSet)
router.register(r'items', ItemViewSet)
router.register(r'purchase-requests', PurchaseRequestViewSet)
router.register(r'purchase-request-items', PurchaseRequestItemViewSet)
router.register(r'supplier-offers', SupplierOfferViewSet)
router.register(r'item-offers', ItemOfferViewSet)
router.register(r'purchase-orders', PurchaseOrderViewSet)

# URL patterns
urlpatterns = [
    path('', include(router.urls)),
    path('status-choices/', StatusChoicesView.as_view(), name="status-list"),
]

# The router will automatically create the following URL patterns:
# 
# Payment Types:
# GET/POST    /api/payment-types/                    - List/Create payment types
# GET/PUT/DELETE /api/payment-types/{id}/            - Retrieve/Update/Delete payment type
# 
# Suppliers:
# GET/POST    /api/suppliers/                        - List/Create suppliers
# GET/PUT/DELETE /api/suppliers/{id}/                - Retrieve/Update/Delete supplier
# GET         /api/suppliers/?name=search            - Search suppliers by name
# 
# Items:
# GET/POST    /api/items/                            - List/Create items
# GET/PUT/DELETE /api/items/{id}/                    - Retrieve/Update/Delete item
# GET         /api/items/?code=search                - Search items by code
# GET         /api/items/?name=search                - Search items by name
# 
# Purchase Requests:
# GET/POST    /api/purchase-requests/                - List/Create purchase requests
# GET/PUT/DELETE /api/purchase-requests/{id}/        - Retrieve/Update/Delete purchase request
# POST        /api/purchase-requests/{id}/submit/    - Submit purchase request
# POST        /api/purchase-requests/{id}/approve/   - Approve purchase request
# POST        /api/purchase-requests/{id}/reject/    - Reject purchase request
# POST        /api/purchase-requests/{id}/complete/  - Complete purchase request
# GET         /api/purchase-requests/my_requests/    - Get user's requests
# GET         /api/purchase-requests/pending_approval/ - Get pending approval requests
# 
# Purchase Request Items:
# GET/POST    /api/purchase-request-items/           - List/Create request items
# GET/PUT/DELETE /api/purchase-request-items/{id}/   - Retrieve/Update/Delete request item
# GET         /api/purchase-request-items/?purchase_request={id} - Get items for specific request
# 
# Supplier Offers:
# GET/POST    /api/supplier-offers/                  - List/Create supplier offers
# GET/PUT/DELETE /api/supplier-offers/{id}/          - Retrieve/Update/Delete supplier offer
# GET         /api/supplier-offers/?purchase_request={id} - Get offers for specific request
# 
# Item Offers:
# GET/POST    /api/item-offers/                      - List/Create item offers
# GET/PUT/DELETE /api/item-offers/{id}/              - Retrieve/Update/Delete item offer
# POST        /api/item-offers/{id}/toggle_recommendation/ - Toggle recommendation
# GET         /api/item-offers/?purchase_request={id} - Get offers for specific request
# GET         /api/item-offers/?supplier_offer={id}   - Get offers for specific supplier
