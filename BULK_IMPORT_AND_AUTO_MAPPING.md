# Bulk Import & Auto-Mapping Features

## Overview

Two new features have been added to streamline the Planning workflow:

1. **Bulk Item Import** - Add multiple items to a PlanningRequest at once
2. **Auto-Mapping Suggestions** - Get catalog item suggestions based on text descriptions

---

## 1. Bulk Item Import

### Endpoint
```
POST /api/procurement/planning-request-items/bulk_create/
```

### Purpose
Allows Planning team to add multiple items to a PlanningRequest in a single API call, instead of creating them one by one.

### Request Body
```json
{
  "planning_request_id": 1,
  "items": [
    {
      "item_code": "PIPE-2IN-STEEL",    // Use item_code OR item_id
      "job_no": "JOB-2024-001",
      "quantity": "50.00",
      "priority": "normal",              // Optional
      "specifications": "2 inch steel"  // Optional
    },
    {
      "item_id": 456,                    // Reference by ID
      "job_no": "JOB-2024-002",
      "quantity": "30.00",
      "specifications": "Special coating"
    },
    {
      "item_code": "WELD-ROD-7018",
      "job_no": "JOB-2024-001",
      "quantity": "25.00",
      "priority": "urgent"
    }
  ]
}
```

### Field Reference

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `planning_request_id` | ✅ Yes | Integer | ID of the PlanningRequest to add items to |
| `items` | ✅ Yes | Array | List of items to create |
| `item_id` | ⚠️ One of | Integer | Catalog item ID |
| `item_code` | ⚠️ One of | String | Catalog item code |
| `job_no` | ✅ Yes | String | Job number for allocation |
| `quantity` | ✅ Yes | Decimal | Quantity (must be > 0) |
| `priority` | ❌ No | String | Priority: `normal`, `urgent`, `critical` (default: `normal`) |
| `specifications` | ❌ No | String | Item-specific specifications |
| `source_item_index` | ❌ No | Integer | Track which DepartmentRequest item this maps to |

⚠️ **Note**: Each item must have **either** `item_id` or `item_code` (not both).

### Response
```json
{
  "detail": "Successfully created 3 items.",
  "planning_request_id": 1,
  "created_count": 3,
  "items": [
    {
      "id": 10,
      "item": 123,
      "item_code": "PIPE-2IN-STEEL",
      "item_name": "Steel Pipe 2\"",
      "item_unit": "metre",
      "job_no": "JOB-2024-001",
      "quantity": "50.00",
      "priority": "normal",
      "specifications": "2 inch steel",
      "order": 1
    },
    // ... more items
  ]
}
```

### Validation Rules

✅ **PlanningRequest must exist and be in `draft` status**
- Cannot add items to `ready` or `converted` requests

✅ **Each item must reference a valid catalog Item**
- By `item_id`: Item must exist
- By `item_code`: Item must exist

✅ **Required fields**
- `job_no` is required
- `quantity` is required and must be > 0

✅ **Order preservation**
- Items are added in the order they appear in the array
- `order` field auto-increments from current max

### Example Use Cases

#### Use Case 1: Bulk Import from Department Request
Planning reviews a DepartmentRequest with 10 items and maps them all at once:

```json
{
  "planning_request_id": 5,
  "items": [
    {
      "item_code": "PIPE-2IN",
      "job_no": "JOB-001",
      "quantity": "100",
      "source_item_index": 0
    },
    {
      "item_code": "WELD-ROD",
      "job_no": "JOB-001",
      "quantity": "50",
      "source_item_index": 1
    },
    // ... 8 more items
  ]
}
```

#### Use Case 2: Multiple Jobs for Same Item
Split a single catalog item across multiple jobs:

```json
{
  "planning_request_id": 5,
  "items": [
    {
      "item_id": 123,
      "job_no": "JOB-2024-001",
      "quantity": "50"
    },
    {
      "item_id": 123,
      "job_no": "JOB-2024-002",
      "quantity": "30"
    },
    {
      "item_id": 123,
      "job_no": "JOB-2024-003",
      "quantity": "20"
    }
  ]
}
```
*Note: When converted to PurchaseRequest, these will merge into one line with 3 allocations.*

### Error Handling

#### Error: Item not found
```json
{
  "items": [
    "Item #0: Item with code 'INVALID-CODE' not found."
  ]
}
```

#### Error: Missing required field
```json
{
  "items": [
    "Item #2: 'job_no' is required."
  ]
}
```

#### Error: Invalid quantity
```json
{
  "items": [
    "Item #1: Quantity must be positive."
  ]
}
```

#### Error: Planning request not in draft
```json
{
  "planning_request_id": [
    "Can only add items to draft planning requests."
  ]
}
```

---

## 2. Auto-Mapping Suggestions

### Endpoint
```
POST /api/procurement/item-suggestions/
```

### Purpose
Suggests catalog items that match a text description using keyword matching. Helps Planning quickly find the right catalog item without manually searching.

### Request Body
```json
{
  "description": "steel pipe 2 inch 100 metres"
}
```

### Response
```json
{
  "description": "steel pipe 2 inch 100 metres",
  "suggestions": [
    {
      "item_id": 123,
      "code": "PIPE-2IN-STEEL",
      "name": "Steel Pipe 2\"",
      "unit": "metre",
      "match_score": 100
    },
    {
      "item_id": 456,
      "code": "PIPE-STL-50MM",
      "name": "Steel Pipe 50mm",
      "unit": "metre",
      "match_score": 66
    },
    {
      "item_id": 789,
      "code": "PIPE-2IN-PVC",
      "name": "PVC Pipe 2\"",
      "unit": "metre",
      "match_score": 33
    }
  ]
}
```

### How It Works

1. **Tokenization**: Description is split into words
2. **Filtering**: Words < 3 characters are ignored (e.g., "a", "in")
3. **Keyword Search**: Searches catalog `Item.name` and `Item.code` for matches
4. **Scoring**: Match score = (matching words / total words) × 100
5. **Ranking**: Results sorted by score (highest first)
6. **Limit**: Returns top 5 suggestions

### Match Score Examples

**Description**: "steel pipe 2 inch"
- `PIPE-2IN-STEEL` (Steel Pipe 2") → **100%** (3/3 words match)
- `PIPE-STL-50MM` (Steel Pipe 50mm) → **66%** (2/3 words match)
- `PIPE-2IN-PVC` (PVC Pipe 2") → **66%** (2/3 words match)
- `BOLT-STEEL` (Steel Bolt) → **33%** (1/3 words match)

### Example Workflow

#### Step 1: Planning reviews DepartmentRequest item
```json
{
  "description": "Welding rods 7018, 3mm diameter, 50kg"
}
```

#### Step 2: Get suggestions
```http
POST /api/procurement/item-suggestions/
{
  "description": "Welding rods 7018, 3mm diameter, 50kg"
}

Response:
{
  "suggestions": [
    {
      "item_id": 999,
      "code": "WELD-ROD-7018",
      "name": "Welding Rod 7018 3mm",
      "unit": "kg",
      "match_score": 100
    },
    {
      "item_id": 888,
      "code": "WELD-7018-4MM",
      "name": "Welding Rod 7018 4mm",
      "unit": "kg",
      "match_score": 75
    }
  ]
}
```

#### Step 3: Use suggestion in bulk import
```http
POST /api/procurement/planning-request-items/bulk_create/
{
  "planning_request_id": 10,
  "items": [
    {
      "item_id": 999,  // ← Selected from suggestions
      "job_no": "JOB-2024-001",
      "quantity": "50"
    }
  ]
}
```

### Limitations

⚠️ **Current implementation uses simple keyword matching**
- Does not handle synonyms (e.g., "steel" ≠ "stainless")
- Does not understand units (e.g., "2 inch" vs "50mm")
- No fuzzy matching for typos
- No semantic understanding

### Future Enhancements

Planned improvements for auto-mapping:

1. **Fuzzy Matching**
   - Handle typos: "stel" → "steel"
   - Use Levenshtein distance

2. **Unit Normalization**
   - "2 inch" = "50mm"
   - "kg" = "kilogram"

3. **Synonym Mapping**
   - "stainless" → "steel"
   - "rod" → "bar"

4. **Machine Learning**
   - Train on historical mappings
   - Learn from Planning's choices
   - Improve over time

5. **Multi-language Support**
   - Turkish ↔ English translation
   - Match descriptions in either language

---

## Combined Workflow Example

### Scenario
Planning receives a DepartmentRequest with 3 items and needs to map them to catalog items.

### Step 1: Create PlanningRequest
```http
POST /api/procurement/planning-requests/
{
  "department_request_id": 100
}

Response: { "id": 10, "status": "draft" }
```

### Step 2: Get suggestions for each item
```http
POST /api/procurement/item-suggestions/
{ "description": "Steel pipes, 2 inch diameter" }
→ Suggests: PIPE-2IN-STEEL (ID: 123)

POST /api/procurement/item-suggestions/
{ "description": "Welding rods, 3mm" }
→ Suggests: WELD-ROD-3MM (ID: 456)

POST /api/procurement/item-suggestions/
{ "description": "Safety gloves, size L" }
→ No match found, Planning creates new item
```

### Step 3: Create new item if needed
```http
POST /api/procurement/items/
{
  "code": "GLOVE-SAFE-L",
  "name": "Safety Gloves Size L",
  "unit": "adet"
}

Response: { "id": 789 }
```

### Step 4: Bulk import all items
```http
POST /api/procurement/planning-request-items/bulk_create/
{
  "planning_request_id": 10,
  "items": [
    {
      "item_id": 123,
      "job_no": "JOB-2024-001",
      "quantity": "100",
      "source_item_index": 0
    },
    {
      "item_id": 456,
      "job_no": "JOB-2024-001",
      "quantity": "50",
      "source_item_index": 1
    },
    {
      "item_id": 789,
      "job_no": "JOB-2024-002",
      "quantity": "20",
      "source_item_index": 2
    }
  ]
}

Response: { "created_count": 3 }
```

### Step 5: Mark ready
```http
POST /api/procurement/planning-requests/10/mark_ready/
```

**Total API calls**: 6 (vs 11+ without bulk import and suggestions)

---

## Permissions

Both features require **Planning team** permission:
- Superuser (`is_superuser=True`), OR
- Planning team member (`profile.team == 'planning'`)

Non-planning users will receive:
```json
{
  "detail": "Only planning team can bulk import items."
}
```

---

## API Summary

| Endpoint | Method | Purpose | Permission |
|----------|--------|---------|------------|
| `/planning-request-items/bulk_create/` | POST | Bulk create items | Planning |
| `/item-suggestions/` | POST | Get item suggestions | Authenticated |

---

## Testing Examples

### cURL Examples

#### Bulk Import
```bash
curl -X POST http://localhost:8000/api/procurement/planning-request-items/bulk_create/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "planning_request_id": 1,
    "items": [
      {
        "item_code": "PIPE-2IN",
        "job_no": "JOB-001",
        "quantity": "50.00"
      }
    ]
  }'
```

#### Item Suggestions
```bash
curl -X POST http://localhost:8000/api/procurement/item-suggestions/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "steel pipe 2 inch"}'
```

### Python Examples

```python
import requests

# Get suggestions
response = requests.post(
    'http://localhost:8000/api/procurement/item-suggestions/',
    headers={'Authorization': f'Bearer {token}'},
    json={'description': 'steel pipe 2 inch'}
)
suggestions = response.json()['suggestions']

# Use first suggestion in bulk import
items_to_create = [
    {
        'item_id': suggestions[0]['item_id'],
        'job_no': 'JOB-2024-001',
        'quantity': '100.00'
    }
]

response = requests.post(
    'http://localhost:8000/api/procurement/planning-request-items/bulk_create/',
    headers={'Authorization': f'Bearer {token}'},
    json={
        'planning_request_id': 10,
        'items': items_to_create
    }
)
print(f"Created {response.json()['created_count']} items")
```

---

## Performance Considerations

### Bulk Import
- ✅ Uses single transaction for all items
- ✅ Validates all items before creating any
- ✅ Orders auto-increment efficiently
- ⚠️ Limit: Recommended max 100 items per request

### Item Suggestions
- ✅ Database query optimized with `distinct()`
- ✅ Limits results to top 10, returns top 5
- ⚠️ Keyword search may be slow on large catalogs
- 💡 **Optimization**: Add database index on `Item.name` and `Item.code`

```sql
-- Recommended indexes (run in Django shell or migration)
CREATE INDEX idx_item_name_trgm ON procurement_item USING gin (name gin_trgm_ops);
CREATE INDEX idx_item_code_trgm ON procurement_item USING gin (code gin_trgm_ops);
```
