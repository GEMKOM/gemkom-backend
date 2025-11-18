# Planning Request - Quick Reference Card

## 🚀 Quick Start

### 1. Planning Creates Request
```bash
POST /api/procurement/planning-requests/
{"department_request_id": 100}
```

### 2. Get Item Suggestions
```bash
POST /api/procurement/item-suggestions/
{"description": "steel pipe 2 inch"}
```

### 3. Bulk Import Items
```bash
POST /api/procurement/planning-request-items/bulk_create/
{
  "planning_request_id": 1,
  "items": [
    {"item_code": "PIPE-2IN", "job_no": "JOB-001", "quantity": "50"},
    {"item_id": 456, "job_no": "JOB-002", "quantity": "30"}
  ]
}
```

### 4. Mark Ready
```bash
POST /api/procurement/planning-requests/1/mark_ready/
```

### 5. Procurement Converts
```bash
POST /api/procurement/planning-requests/1/convert_to_purchase_request/
```

---

## 📋 All Endpoints

### Planning Team Only
```
POST   /planning-requests/                        # Create from DepartmentRequest
GET    /planning-requests/                        # List all
GET    /planning-requests/my_requests/            # My requests
POST   /planning-requests/{id}/mark_ready/        # Mark as ready

POST   /planning-request-items/                   # Add single item
PATCH  /planning-request-items/{id}/              # Edit item
DELETE /planning-request-items/{id}/              # Delete item
POST   /planning-request-items/bulk_create/       # Bulk add items
```

### Procurement Team Only
```
GET    /planning-requests/ready_for_procurement/  # List ready requests
POST   /planning-requests/{id}/convert_to_purchase_request/  # Convert to PR
```

### All Authenticated
```
POST   /item-suggestions/                         # Get item suggestions
```

---

## 🔄 Status Flow

```
draft → ready → converted
```

- **draft**: Planning is mapping items
- **ready**: Ready for procurement to convert
- **converted**: Already converted to PurchaseRequest (immutable)

---

## 📊 Request Body Examples

### Create Planning Request
```json
{
  "department_request_id": 100
}
```

### Add Single Item
```json
{
  "planning_request": 1,
  "item_id": 123,
  "job_no": "JOB-2024-001",
  "quantity": "50.00",
  "priority": "normal",
  "specifications": "Optional specs"
}
```

### Bulk Import Items
```json
{
  "planning_request_id": 1,
  "items": [
    {
      "item_code": "PIPE-2IN",
      "job_no": "JOB-001",
      "quantity": "50.00",
      "priority": "urgent"
    },
    {
      "item_id": 456,
      "job_no": "JOB-002",
      "quantity": "30.00"
    }
  ]
}
```

### Get Suggestions
```json
{
  "description": "steel pipe 2 inch 100 metres"
}
```

---

## ✅ Validation Rules

### Planning Request
- ✅ Must have items before marking ready
- ✅ All items must have valid catalog Item
- ✅ All quantities must be > 0
- ✅ All items must have job_no

### Bulk Import
- ✅ Each item needs `item_id` OR `item_code`
- ✅ `job_no` is required
- ✅ `quantity` is required and > 0
- ✅ Planning request must be in `draft` status

---

## 🎯 Common Workflows

### Workflow 1: From Department Request
```
1. DepartmentRequest approved
2. Planning: Create PlanningRequest
3. Planning: Use suggestions to find items
4. Planning: Bulk import all items
5. Planning: Mark ready
6. Procurement: Convert to PR
7. Procurement: Add offers, submit
```

### Workflow 2: Direct Planning Request
```
1. Planning: Create empty PlanningRequest
2. Planning: Add items one by one
3. Planning: Mark ready
4. Procurement: Convert to PR
5. Procurement: Add offers, submit
```

### Workflow 3: Mixed Approach
```
1. Planning: Create PlanningRequest
2. Planning: Add some items individually
3. Planning: Get suggestions for remaining
4. Planning: Bulk import rest
5. Planning: Mark ready
6. Procurement: Convert to PR
```

---

## 🔐 Permissions

| Team | Can Create | Can Edit Items | Can Mark Ready | Can Convert |
|------|------------|----------------|----------------|-------------|
| **Planning** | ✅ | ✅ | ✅ | ❌ |
| **Procurement** | ❌ | ❌ | ❌ | ✅ |
| **Superuser** | ✅ | ✅ | ✅ | ✅ |

---

## 🐛 Common Errors

### "Planning request not found"
- Check `planning_request_id` is correct
- Ensure request exists

### "Can only add items to draft planning requests"
- Request is already `ready` or `converted`
- Create new request or change status back

### "Item #X: Item with code 'Y' not found"
- Catalog item doesn't exist
- Create item first or use correct code

### "Can only convert planning requests with status 'ready'"
- Mark request as ready first
- Ensure validation passes

### "Cannot mark empty planning request as ready"
- Add at least one item
- Use bulk import or individual create

---

## 💡 Pro Tips

### For Planning Team
1. **Use suggestions first** - Faster than searching manually
2. **Bulk import when possible** - Much faster than one-by-one
3. **Create items ahead** - Pre-populate catalog for common items
4. **Use specifications** - Add details for procurement

### For Procurement Team
1. **Check ready list** - `/ready_for_procurement/` endpoint
2. **Convert immediately** - Don't let requests pile up
3. **Review allocations** - Ensure job numbers are correct

### For Everyone
1. **Check permissions** - Ensure `profile.team` is set correctly
2. **Read error messages** - They tell you exactly what's wrong
3. **Use admin interface** - Good for debugging and manual fixes

---

## 📖 Full Documentation

- **Workflow Guide**: [PLANNING_REQUEST_IMPLEMENTATION.md](PLANNING_REQUEST_IMPLEMENTATION.md)
- **Advanced Features**: [BULK_IMPORT_AND_AUTO_MAPPING.md](BULK_IMPORT_AND_AUTO_MAPPING.md)
- **Summary**: [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)

---

## 🆘 Need Help?

1. Check the error message
2. Review this quick reference
3. Check full documentation
4. Use Django admin for debugging
5. Check database migrations are run

---

## ⚡ Performance Tips

### For Large Imports
- Bulk import up to 100 items per request
- Split larger batches into multiple calls
- Use `item_id` instead of `item_code` (faster lookup)

### For Suggestions
- Keep descriptions concise
- Use meaningful keywords (>= 3 chars)
- Results limited to top 5 automatically

---

## 🎉 You're Ready!

Start with:
```bash
# 1. Run migrations
python manage.py makemigrations procurement
python manage.py migrate

# 2. Create a planning request
curl -X POST http://localhost:8000/api/procurement/planning-requests/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"department_request_id": 1}'

# 3. Get suggestions
curl -X POST http://localhost:8000/api/procurement/item-suggestions/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"description": "steel pipe"}'
```

Good luck! 🚀
