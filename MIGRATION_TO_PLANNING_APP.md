# Migration to Planning App - Summary

## ✅ What Was Done

All planning-related functionality has been moved from `procurement` app to the new `planning` app for better separation of concerns.

### Files Created in `planning/` App

1. **`planning/models.py`** - PlanningRequest & PlanningRequestItem models
2. **`planning/services.py`** - Business logic functions
3. **`planning/serializers.py`** - All planning serializers
4. **`planning/views.py`** - ViewSets and API views
5. **`planning/urls.py`** - URL routing
6. **`planning/admin.py`** - Admin interface

### Key Changes

**Models moved:**
- `PlanningRequest` → `planning.models.PlanningRequest`
- `PlanningRequestItem` → `planning.models.PlanningRequestItem`

**Foreign Keys updated to use string references:**
- `department_request = ForeignKey('procurement.DepartmentRequest', ...)`
- `purchase_request = ForeignKey('procurement.PurchaseRequest', ...)`
- `item = ForeignKey('procurement.Item', ...)`

## 🔧 Required Manual Steps

### 1. Remove Old Code from Procurement App

Delete or comment out the following from `procurement/` files:

#### In `procurement/models.py`:
- Remove `PlanningRequest` class (lines 507-587)
- Remove `PlanningRequestItem` class (lines 589-622)

#### Files to delete:
- `procurement/planning_service.py` (entire file - moved to `planning/services.py`)

#### In `procurement/serializers.py`:
- Remove `PlanningRequestItemSerializer` class
- Remove `PlanningRequestSerializer` class
- Remove `PlanningRequestCreateSerializer` class
- Remove `BulkPlanningRequestItemSerializer` class

#### In `procurement/views.py`:
- Remove `PlanningRequestViewSet` class
- Remove `PlanningRequestItemViewSet` class
- Remove `ItemSuggestionView` class (moved to `planning/views.py`)

#### In `procurement/urls.py`:
- Remove planning-related routes:
  ```python
  router.register(r'planning-requests', PlanningRequestViewSet)
  router.register(r'planning-request-items', PlanningRequestItemViewSet)
  path('item-suggestions/', ItemSuggestionView.as_view(), ...)
  ```

#### In `procurement/admin.py`:
- Remove `PlanningRequestItemInline` class
- Remove `PlanningRequestAdmin` class
- Remove `PlanningRequest` and `PlanningRequestItem` from imports

### 2. Update Main URLs

Add planning app to your main `urls.py`:

```python
# In your main urls.py (e.g., config/urls.py or project/urls.py)
urlpatterns = [
    # ... existing paths ...
    path('api/planning/', include('planning.urls')),
    # ... other paths ...
]
```

### 3. Add to INSTALLED_APPS

Ensure `planning` is in `INSTALLED_APPS` in settings.py:

```python
INSTALLED_APPS = [
    # ...
    'planning',  # ← Add this
    'procurement',
    # ...
]
```

### 4. Create & Run Migrations

```bash
# Create migrations for the new planning app
python manage.py makemigrations planning

# If there's an error about forward references, you may need to:
python manage.py makemigrations procurement  # Remove old models
python manage.py makemigrations planning     # Add new models

# Then migrate
python manage.py migrate
```

### 5. Update Import Statements

Any code that imported planning models from procurement needs updating:

**Before:**
```python
from procurement.models import PlanningRequest, PlanningRequestItem
from procurement.planning_service import create_planning_request_from_department
```

**After:**
```python
from planning.models import PlanningRequest, PlanningRequestItem
from planning.services import create_planning_request_from_department
```

## 📍 New API Endpoints

All planning endpoints now under `/api/planning/`:

| Old URL | New URL |
|---------|---------|
| `/api/procurement/planning-requests/` | `/api/planning/requests/` |
| `/api/procurement/planning-request-items/` | `/api/planning/items/` |
| `/api/procurement/item-suggestions/` | `/api/planning/item-suggestions/` |

### Full Endpoint List

```
GET/POST    /api/planning/requests/                          - List/Create planning requests
GET         /api/planning/requests/{id}/                     - Retrieve planning request
POST        /api/planning/requests/{id}/mark_ready/          - Mark as ready
POST        /api/planning/requests/{id}/convert_to_purchase_request/  - Convert (Procurement)
GET         /api/planning/requests/my_requests/              - My requests
GET         /api/planning/requests/ready_for_procurement/    - Ready list (Procurement)

GET/POST    /api/planning/items/                             - List/Create items
PATCH/DELETE /api/planning/items/{id}/                       - Update/Delete item
POST        /api/planning/items/bulk_create/                 - Bulk import

POST        /api/planning/item-suggestions/                  - Get suggestions
```

## ✅ Benefits of This Structure

1. **Separation of Concerns**: Planning logic is completely separate from procurement
2. **Better Organization**: Each app has clear responsibility
3. **Easier Maintenance**: Changes to planning don't affect procurement
4. **Cleaner URLs**: `/api/planning/` vs `/api/procurement/planning-`
5. **Independent Testing**: Can test planning features in isolation

## 🔄 Backward Compatibility

If you have existing frontend code calling the old endpoints, you have two options:

### Option 1: Update Frontend (Recommended)
Update all API calls from `/api/procurement/planning-*` to `/api/planning/*`

### Option 2: Add URL Redirects (Temporary)
Add redirects in `procurement/urls.py`:
```python
from django.views.generic import RedirectView

urlpatterns = [
    # ... existing patterns ...
    path('planning-requests/', RedirectView.as_view(url='/api/planning/requests/', permanent=False)),
    # ... other redirects ...
]
```

## 🧪 Testing Checklist

After migration, test:

- [ ] Can create PlanningRequest from DepartmentRequest
- [ ] Can add items individually
- [ ] Can bulk import items
- [ ] Can get item suggestions
- [ ] Can mark request as ready
- [ ] Procurement can convert to PurchaseRequest
- [ ] Admin interface works
- [ ] All endpoints accessible at new URLs
- [ ] Permissions work correctly

## 📝 Notes

- Database table names will be `planning_planningrequest` and `planning_planningrequestitem`
- Foreign keys to procurement models use string references to avoid circular imports
- All existing data will need migration if you had planning data in procurement tables

