# Remnant Plate Migration Guide

## Overview

The remnant plate system has been updated from a simple ForeignKey relationship to a ManyToMany relationship with a through model. This allows:

1. **Tracking quantity used**: Each CNC task can specify how many plates it uses from a remnant plate
2. **Multiple tasks per plate**: A remnant plate with quantity > 1 can be shared across multiple tasks
3. **Usage history**: Track when and which tasks used which plates

## Changes Made

### 1. Models ([cnc_cutting/models.py](cnc_cutting/models.py))

- **Added `RemnantPlateUsage` model**: Through model to track plate usage
  - `cnc_task`: ForeignKey to CncTask
  - `remnant_plate`: ForeignKey to RemnantPlate
  - `quantity_used`: How many plates were consumed (default: 1)
  - `assigned_date`: When the plate was assigned

- **Updated `RemnantPlate` model**:
  - Added `available_quantity()` method: Returns remaining quantity after usage

- **Updated `CncTask` model**:
  - Removed: `selected_plate` ForeignKey field
  - Added: `remnant_plates` ManyToManyField through RemnantPlateUsage

### 2. Serializers ([cnc_cutting/serializers.py](cnc_cutting/serializers.py))

- **RemnantPlateSerializer**: Now includes `available_quantity` field

- **RemnantPlateUsageSerializer**: New serializer for the through model
  - Returns plate details and usage information

- **CncTaskDetailSerializer**: Updated to handle new relationship
  - Read-only field: `plate_usage_records` (list of RemnantPlateUsage)
  - Write-only fields: `selected_plate_id`, `quantity_used`
  - Maintains backward compatibility with single plate selection

### 3. Views ([cnc_cutting/views.py](cnc_cutting/views.py))

- **RemnantPlateViewSet**: Updated get_queryset to show only plates with available quantity
  - Uses annotation to calculate total usage and compare with quantity

- **CncTaskViewSet**: Added prefetch for `plate_usage_records__remnant_plate`

### 4. Migration Command

Created management command: `migrate_remnant_plates`

## Migration Steps

### Step 1: Run the data migration command

Before running Django migrations, execute the data migration command:

```bash
# Dry run to see what will be migrated
python manage.py migrate_remnant_plates --dry-run

# Actually perform the migration
python manage.py migrate_remnant_plates
```

This command will:
- Find all CncTasks with a selected_plate
- Create RemnantPlateUsage records with quantity_used=1
- Set remnant plate quantity to 1 if it was greater than 1

### Step 2: Run Django migrations

```bash
python manage.py migrate cnc_cutting
```

This will apply migration 0017 which:
- Removes the `selected_plate` field
- Creates the `RemnantPlateUsage` table
- Adds the `remnant_plates` ManyToMany field

## API Usage

### Creating a CNC Task with a Remnant Plate

```javascript
// POST /api/cnc_cutting/tasks/
{
  "name": "Test Task",
  "nesting_id": "N123",
  "selected_plate_id": 5,      // The remnant plate to use
  "quantity_used": 1,           // Optional, defaults to 1
  // ... other fields
}
```

### Updating a CNC Task's Remnant Plate

```javascript
// PATCH /api/cnc_cutting/tasks/{key}/
{
  "selected_plate_id": 7,      // Change to a different plate
  "quantity_used": 1
}

// To remove plate assignment
{
  "selected_plate_id": null
}
```

### Retrieving Task with Plate Information

```javascript
// GET /api/cnc_cutting/tasks/{key}/
{
  "key": "CNC-001",
  "name": "Test Task",
  "plate_usage_records": [
    {
      "id": 1,
      "remnant_plate": 5,
      "remnant_plate_details": {
        "id": 5,
        "thickness_mm": "10.00",
        "dimensions": "2000x1000",
        "quantity": 3,
        "material": "Steel",
        "available_quantity": 2    // 3 total - 1 used = 2 available
      },
      "quantity_used": 1,
      "assigned_date": "2026-01-09T06:30:00Z"
    }
  ],
  // ... other fields
}
```

### Listing Available Remnant Plates

```javascript
// GET /api/cnc_cutting/remnants/
// Returns only plates with available_quantity > 0
[
  {
    "id": 5,
    "thickness_mm": "10.00",
    "dimensions": "2000x1000",
    "quantity": 3,
    "material": "Steel",
    "available_quantity": 2
  }
]

// To see all plates (including fully used)
// GET /api/cnc_cutting/remnants/?unassigned=false
```

## Backward Compatibility

The API maintains backward compatibility:
- Frontend can still use `selected_plate_id` to assign a single plate
- The system automatically creates/updates RemnantPlateUsage records
- Default `quantity_used` is 1, matching previous behavior

## Future Enhancements

Possible future improvements:
1. Allow multiple plate assignments per task (currently limited to one via the update logic)
2. Add validation to prevent over-allocation (using more quantity than available)
3. Add reporting endpoints for plate usage analytics
4. Implement plate reservation system

## Troubleshooting

### Migration command says field doesn't exist
If you've already run migration 0017, the `selected_plate` field will be gone. The command detects this and checks for existing RemnantPlateUsage records.

### Plates showing as unavailable
Check the `available_quantity` field - it calculates based on:
```python
available = plate.quantity - sum(usage_records.quantity_used)
```

### Task shows no plate_usage_records
Ensure the task was migrated properly. Check:
```bash
python manage.py shell
>>> from cnc_cutting.models import CncTask, RemnantPlateUsage
>>> task = CncTask.objects.get(key='CNC-001')
>>> task.plate_usage_records.all()
```
