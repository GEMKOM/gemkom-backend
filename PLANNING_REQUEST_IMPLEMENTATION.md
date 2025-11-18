# Planning Request Implementation Guide

## Overview

This implementation adds a **Planning Request** workflow between Department Requests and Purchase Requests, allowing the Planning team to map raw item requests to actual catalog items.

## Workflow

```
┌─────────────────────┐
│ DepartmentRequest   │  ← Any department creates raw request
│ (Free-form items)   │
└──────────┬──────────┘
           │
           ▼ (Department head approves)
           │
           ▼
┌─────────────────────┐
│ PlanningRequest     │  ← Planning maps to catalog Items
│ (Structured items)  │     - Creates/selects Items
└──────────┬──────────┘     - Assigns job_no + quantity
           │
           ▼ (Planning marks ready)
           │
           ▼
┌─────────────────────┐
│ PurchaseRequest     │  ← Procurement adds offers
│ (Items + Offers)    │     - Gets supplier quotes
└──────────┬──────────┘     - Submits for approval
           │
           ▼ (Approval workflow)
           │
           ▼
┌─────────────────────┐
│ PurchaseOrder       │  ← Auto-created on approval
└─────────────────────┘
```

## Models Added

### 1. PlanningRequest
- **Purpose**: Planning-managed request with catalog items
- **Status Flow**: `draft` → `ready` → `converted`
- **Key Fields**:
  - `request_number`: Auto-generated (PLR-YYYY-NNNN)
  - `department_request`: Link to source (optional)
  - `purchase_request`: Link to result (after conversion)
  - `created_by`: Planning user who created it
  - `ready_at`: When marked ready for procurement
  - `converted_at`: When converted to PR

### 2. PlanningRequestItem
- **Purpose**: Individual item line (one item + one job)
- **Key Fields**:
  - `item`: FK to catalog Item
  - `job_no`: Job allocation
  - `quantity`: Decimal quantity
  - `priority`, `specifications`: Item-level overrides
  - `source_item_index`: Track which DepartmentRequest item this came from

## API Endpoints

### Planning Team Endpoints

#### Create Planning Request from Department Request
```http
POST /api/procurement/planning-requests/
Content-Type: application/json

{
  "department_request_id": 123
}
```

#### Get All Planning Requests (Planning team only)
```http
GET /api/procurement/planning-requests/
```

#### Get My Planning Requests
```http
GET /api/procurement/planning-requests/my_requests/
```

#### Add/Edit Items
```http
POST /api/procurement/planning-request-items/
Content-Type: application/json

{
  "planning_request": 1,
  "item_id": 456,
  "job_no": "JOB-2024-001",
  "quantity": "50.00",
  "priority": "normal",
  "specifications": "Optional specs"
}
```

```http
PATCH /api/procurement/planning-request-items/1/
Content-Type: application/json

{
  "quantity": "75.00"
}
```

#### Mark Ready for Procurement
```http
POST /api/procurement/planning-requests/1/mark_ready/
```

### Procurement Team Endpoints

#### Get Ready Planning Requests
```http
GET /api/procurement/planning-requests/ready_for_procurement/
```

#### Convert to Purchase Request
```http
POST /api/procurement/planning-requests/1/convert_to_purchase_request/

Response:
{
  "detail": "Successfully converted to purchase request.",
  "purchase_request_id": 789,
  "request_number": "PR-2024-0123"
}
```

## Service Functions

### Planning Service (`procurement/planning_service.py`)

#### `create_planning_request_from_department(dept_request, created_by_user)`
- Creates PlanningRequest from approved DepartmentRequest
- Marks DepartmentRequest as 'transferred'
- Returns empty PlanningRequest (Planning adds items manually)

#### `mark_planning_request_ready(planning_request)`
- Validates all items are mapped
- Validates quantities > 0 and job_no present
- Changes status to 'ready'
- Sets `ready_at` timestamp

#### `convert_planning_request_to_purchase_request(planning_request, converted_by_user)`
- Groups items by (item, priority, specifications)
- Creates PurchaseRequest with merged items
- Creates PurchaseRequestItemAllocations for each job_no
- Marks PlanningRequest as 'converted'
- Returns PurchaseRequest (in 'draft' status for offers)

## Example: Complete Workflow

### 1. Department Creates Request
```http
POST /api/procurement/department-requests/
{
  "title": "Maintenance Materials",
  "items": [
    {
      "description": "Steel pipes, 2 inch diameter",
      "quantity": 100,
      "unit": "metre"
    },
    {
      "description": "Welding rods",
      "quantity": 50,
      "unit": "kg"
    }
  ]
}
```

### 2. Department Head Approves
```http
POST /api/procurement/department-requests/1/approve/
```

### 3. Planning Creates PlanningRequest
```http
POST /api/procurement/planning-requests/
{
  "department_request_id": 1
}

Response: { "id": 10, "request_number": "PLR-2024-0001", "status": "draft" }
```

### 4. Planning Maps Items to Catalog
```http
# Option A: Item exists in catalog
POST /api/procurement/planning-request-items/
{
  "planning_request": 10,
  "item_id": 456,  # Existing catalog item "PIPE-2IN-STEEL"
  "job_no": "JOB-2024-001",
  "quantity": "60.00",
  "specifications": "2 inch steel pipe"
}

# Option B: Create new catalog item first
POST /api/procurement/items/
{
  "code": "WELD-ROD-7018",
  "name": "Welding Rod 7018",
  "unit": "kg"
}

# Then map it
POST /api/procurement/planning-request-items/
{
  "planning_request": 10,
  "item_id": 789,  # Newly created item
  "job_no": "JOB-2024-001",
  "quantity": "50.00"
}
```

### 5. Planning Marks Ready
```http
POST /api/procurement/planning-requests/10/mark_ready/
```

### 6. Procurement Converts to PR
```http
POST /api/procurement/planning-requests/10/convert_to_purchase_request/

Response:
{
  "purchase_request_id": 123,
  "request_number": "PR-2024-0050"
}
```

### 7. Procurement Adds Offers & Submits
```http
# Procurement uses existing workflow to add supplier offers
PATCH /api/procurement/purchase-requests/123/
{
  # Add supplier offers, recommendations, etc.
}

POST /api/procurement/purchase-requests/123/submit/
```

## Database Migration

Run these commands to create and apply migrations:

```bash
# Activate virtual environment first
# Then:

python manage.py makemigrations procurement
python manage.py migrate procurement
```

## Permissions

### Planning Team (`profile.team == 'planning'`)
- Create PlanningRequest from DepartmentRequest
- Add/edit PlanningRequestItems
- Mark PlanningRequest as ready
- View all PlanningRequests

### Procurement Team (`IsFinanceAuthorized`)
- View ready PlanningRequests
- Convert PlanningRequest to PurchaseRequest
- Cannot edit PlanningRequest or items

### Superusers
- Full access to all operations

## Important Notes

### Item Grouping Logic
When converting to PurchaseRequest, items are grouped by:
- `item.id` (catalog item)
- `priority`
- `specifications`

Items with same (item, priority, specs) but different job_no are **merged** into one PurchaseRequestItem with multiple allocations.

**Example:**
```
PlanningRequestItems:
  - Item: PIPE-2IN, Job: JOB-001, Qty: 50
  - Item: PIPE-2IN, Job: JOB-002, Qty: 30
  - Item: PIPE-2IN, Job: JOB-003, Qty: 20

Becomes:
  PurchaseRequestItem:
    - Item: PIPE-2IN, Qty: 100
    - Allocations:
      - JOB-001: 50
      - JOB-002: 30
      - JOB-003: 20
```

### Status Transitions

**PlanningRequest:**
- `draft` → Planning is mapping items
- `ready` → Ready for procurement to convert
- `converted` → Already converted to PR (immutable)
- `cancelled` → Cancelled by planning

**DepartmentRequest:**
- When PlanningRequest is created, DepartmentRequest.status changes to `'transferred'`

### Validation

`mark_ready()` validates:
- At least one item exists
- All items have valid `item` (catalog FK)
- All quantities > 0
- All items have `job_no`

`convert_to_purchase_request()` validates:
- Status must be `'ready'`
- At least one item exists

## Admin Interface

Navigate to `/admin/procurement/planningrequest/` to:
- View all planning requests
- Edit items inline
- Track conversion status
- See source DepartmentRequest and resulting PurchaseRequest

## Testing Checklist

- [ ] Planning can create PlanningRequest from approved DepartmentRequest
- [ ] Planning can add items with existing catalog Items
- [ ] Planning can create new catalog Items and map them
- [ ] Planning can edit item quantities, job_no, specifications
- [ ] mark_ready validates properly (rejects empty, invalid items)
- [ ] Procurement sees only 'ready' requests
- [ ] Conversion groups items correctly
- [ ] Conversion creates proper allocations
- [ ] PurchaseRequest starts in 'draft' status
- [ ] Converted PlanningRequest becomes immutable
- [ ] DepartmentRequest status updates to 'transferred'

## Advanced Features

### ✅ Bulk Item Import
Planning can add multiple items at once instead of creating them one by one.

**Endpoint**: `POST /api/procurement/planning-request-items/bulk_create/`

See [BULK_IMPORT_AND_AUTO_MAPPING.md](BULK_IMPORT_AND_AUTO_MAPPING.md) for detailed documentation.

**Example**:
```json
{
  "planning_request_id": 1,
  "items": [
    {"item_code": "PIPE-2IN", "job_no": "JOB-001", "quantity": "50"},
    {"item_id": 456, "job_no": "JOB-002", "quantity": "30"}
  ]
}
```

### ✅ Auto-Mapping Suggestions
Get catalog item suggestions based on text descriptions using keyword matching.

**Endpoint**: `POST /api/procurement/item-suggestions/`

**Example**:
```json
Request:
{ "description": "steel pipe 2 inch" }

Response:
{
  "suggestions": [
    {
      "item_id": 123,
      "code": "PIPE-2IN-STEEL",
      "name": "Steel Pipe 2\"",
      "match_score": 100
    }
  ]
}
```

See [BULK_IMPORT_AND_AUTO_MAPPING.md](BULK_IMPORT_AND_AUTO_MAPPING.md) for full documentation.

## Future Enhancements

1. **Enhanced auto-mapping**: Fuzzy matching, synonyms, unit normalization
2. **ML-based suggestions**: Train on historical mappings to improve accuracy
3. **CSV upload**: Bulk import from Excel/CSV files
4. **Item templates**: Save common item combinations for faster mapping
5. **Approval for expensive items**: Planning approval before procurement
6. **Analytics**: Track mapping quality, time-to-convert metrics
