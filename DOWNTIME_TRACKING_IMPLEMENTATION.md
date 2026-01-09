# Downtime Tracking Implementation

## Overview

This implementation adds comprehensive time tracking to minimize blank time by tracking not just productive work, but also breaks, lunch, downtime (waiting for materials/tools/machine fixes), and other non-productive time.

## Key Features

### 1. **Timer Types**
- **Productive**: Normal work timers (existing behavior, default)
- **Break**: Lunch breaks and short breaks
- **Downtime**: Waiting for materials, tools, machine issues, setup/changeover, etc.

### 2. **Automatic Fault Handling & Machine-Level Downtime**

**Machine-Level Tracking:**
- When a breaking fault is reported, `downtime_start_ms` is recorded
- When the fault is resolved, `downtime_end_ms` is recorded
- This tracks **total machine unavailability** regardless of whether anyone was working
- Important for: machine utilization rates, MTTR/MTBF metrics, capacity planning

**Operator-Level Tracking (if operators are working):**
When a breaking machine fault is reported:
1. All active productive timers on that machine are automatically stopped
2. Downtime timers are automatically started for each stopped timer
3. Downtime timers are linked to the machine fault
4. Operators can track their waiting time

When the fault is resolved:
1. All downtime timers linked to that fault are automatically stopped
2. Operators can then manually start new productive timers when ready

**If no one is working when fault occurs:**
- Machine downtime is still tracked (downtime_start_ms → downtime_end_ms)
- No operator timers are created (correct - no one was affected)
- Machine availability metrics remain accurate

### 3. **Operator Workflow**

#### Starting Work
- Operator starts a timer on an operation (same as before)
- Timer is created with `timer_type='productive'` (default)

#### Stopping for a Reason
When operator stops a timer, they select a reason:
- 🍽️ **Lunch Break** → Creates lunch timer
- ☕ **Break** → Creates break timer
- 🏠 **End of Shift** → Just stops, no new timer
- 📦 **Waiting Materials** → Creates downtime timer
- 🔨 **Waiting Tools** → Creates downtime timer
- 🔧 **Machine Issue** → Creates downtime timer (can link to fault)
- ⚙️ **Setup/Changeover** → Creates downtime timer
- ✅ **Work Complete** → Just stops, no new timer
- ❓ **Other** → Creates downtime timer

#### Machine Breaks (Automatic)
1. Someone reports a breaking fault on the machine
2. System automatically:
   - Stops all productive timers on that machine
   - Starts downtime timers linked to the fault
3. When fault is resolved:
   - System stops all downtime timers
4. Operator manually starts new productive timer when ready to work

## Database Schema Changes

### New Model: `DowntimeReason`
```python
class DowntimeReason(models.Model):
    code = CharField(max_length=50, unique=True)  # e.g., 'LUNCH', 'MACHINE_FAULT'
    name = CharField(max_length=100)  # e.g., 'Lunch Break', 'Machine Issue'
    category = CharField(max_length=20)  # 'break', 'downtime', 'complete'
    creates_timer = BooleanField(default=True)  # Whether to start a new timer
    requires_fault_reference = BooleanField(default=False)  # Must link to fault
    display_order = PositiveIntegerField(default=100)  # UI ordering
    is_active = BooleanField(default=True)
```

### Updated Model: `Timer`
New fields added:
```python
timer_type = CharField(choices=['productive', 'break', 'downtime'], default='productive')
downtime_reason = ForeignKey(DowntimeReason, null=True, blank=True)
related_fault = ForeignKey(MachineFault, null=True, blank=True)
```

**All existing timers are preserved!** The migration sets `timer_type='productive'` as default, so all old timers remain productive timers.

### Updated Model: `MachineFault`
New fields added for machine-level downtime tracking:
```python
downtime_start_ms = BigIntegerField(null=True, blank=True)  # When machine became unavailable
downtime_end_ms = BigIntegerField(null=True, blank=True)    # When machine became available again
```

Property added:
```python
@property
def downtime_hours(self) -> float:
    """Calculate machine downtime in hours"""
    if self.downtime_start_ms and self.downtime_end_ms:
        return (self.downtime_end_ms - self.downtime_start_ms) / 3600000.0
    return 0.0
```

**Machine downtime is tracked automatically:**
- Set when `is_breaking=True` fault is reported
- Completed when fault is resolved
- Tracks total machine unavailability regardless of operator activity

## API Changes

### New Endpoint: Get Downtime Reasons
```
GET /tasks/downtime-reasons/
```
Returns list of active downtime reasons for operator UI.

Response:
```json
[
  {
    "id": 1,
    "code": "LUNCH",
    "name": "Lunch Break",
    "category": "break",
    "category_display": "Break/Lunch",
    "creates_timer": true,
    "requires_fault_reference": false,
    "display_order": 1,
    "is_active": true
  },
  ...
]
```

### New Endpoint: Log Reason (Unified Workflow)
```
POST /tasks/log-reason/
```

Unified endpoint for logging downtime/break reasons. Handles both scenarios:
1. User has active timer and wants to stop it with a reason
2. User has no active timer but wants to log a reason (e.g., machine fault when not working)

**Request:**
```json
{
  "current_timer_id": 123,           // Optional - timer to stop
  "reason_id": 4,                    // Required - DowntimeReason ID
  "comment": "Waiting for steel",    // Optional - description
  "machine_id": 5,                   // Required if no current_timer_id
  "operation_key": "PT-001-OP-1"     // Required if no current_timer_id
}
```

**Response:**
```json
{
  "stopped_timer_id": 123,           // ID of stopped timer (if applicable)
  "new_timer_id": 124,               // ID of new timer (if created)
  "timer": {                         // Full timer object (if created)
    "id": 124,
    "user": 5,
    "timer_type": "downtime",
    "downtime_reason": 4,
    "downtime_reason_code": "MACHINE_FAULT",
    "downtime_reason_name": "Arıza",
    "related_fault": 45,
    "related_fault_id": 45,
    "can_be_stopped_by_user": false,
    // ... other timer fields
  },
  "fault_id": 45,                    // ID of created fault (if applicable)
  "operation_completed": true,       // If operation was marked complete
  "message": "Timer stopped and downtime timer started"
}
```

**Workflow:**
- If `current_timer_id` provided: validates user can stop it, then stops the timer
- **MACHINE_FAULT handling:**
  - Creates MachineFault ticket and sends Telegram notification
  - Always creates downtime timer linked to fault (cannot be manually stopped)
  - If stopping productive timer: creates fault-linked downtime timer
  - If no active timer: creates fault-linked downtime timer for tracking
- **WORK_COMPLETE handling:**
  - Marks the operation as complete (sets `completion_date` and `completed_by`)
  - Only works with Operation timers (not machining or CNC tasks)
  - Does NOT create new timer (reason has `creates_timer: false`)
- If reason `creates_timer` is true: starts new timer (break/downtime) and returns full timer object
- Fault-related timers (`related_fault_id != null`) cannot be manually stopped (returns 403 error)
- Returns comprehensive response with IDs and full timer object for newly created timers

### Updated Timer Endpoints
All existing timer endpoints now include new fields in responses:
- `timer_type`: 'productive', 'break', or 'downtime'
- `downtime_reason`: ID of reason (if applicable)
- `downtime_reason_code`: Code like 'LUNCH', 'MACHINE_FAULT' (read-only)
- `downtime_reason_name`: Display name (read-only)
- `related_fault`: ID of machine fault (if applicable)
- `related_fault_id`: Fault ID (read-only)

### Timer Creation with Downtime
To create a downtime timer:
```json
POST /tasks/timers/start/operation
{
  "task_key": "PT-001-OP-1",
  "machine_fk": 5,
  "start_time": 1704067200000,
  "timer_type": "downtime",
  "downtime_reason": 4,  // ID of downtime reason
  "comment": "Waiting for steel delivery"
}
```

## Migration Steps

### 1. Run Migrations
```bash
python manage.py makemigrations tasks
python manage.py migrate tasks
```

This will:
- Create the `DowntimeReason` table
- Add new fields to `Timer` table
- Set all existing timers to `timer_type='productive'` (preserves old data)

### 2. Populate Default Reasons
The data migration file `populate_downtime_reasons.py` needs to be run.

**Important**: Update the dependency in the migration file:
```python
dependencies = [
    ('tasks', 'XXXX_add_downtime_tracking'),  # Replace with actual migration number
]
```

Then run:
```bash
python manage.py migrate tasks
```

Or manually create reasons:
```bash
python manage.py shell
from tasks.models import DowntimeReason

reasons = [
    {'code': 'LUNCH', 'name': 'Lunch Break', 'category': 'break', 'creates_timer': True, 'display_order': 1},
    {'code': 'BREAK', 'name': 'Break', 'category': 'break', 'creates_timer': True, 'display_order': 2},
    {'code': 'END_SHIFT', 'name': 'End of Shift', 'category': 'break', 'creates_timer': False, 'display_order': 3},
    {'code': 'WAITING_MATERIALS', 'name': 'Waiting for Materials', 'category': 'downtime', 'creates_timer': True, 'display_order': 10},
    {'code': 'WAITING_TOOLS', 'name': 'Waiting for Tools', 'category': 'downtime', 'creates_timer': True, 'display_order': 11},
    {'code': 'MACHINE_FAULT', 'name': 'Machine Issue', 'category': 'downtime', 'creates_timer': True, 'requires_fault_reference': True, 'display_order': 12},
    {'code': 'SETUP', 'name': 'Setup/Changeover', 'category': 'downtime', 'creates_timer': True, 'display_order': 13},
    {'code': 'OTHER', 'name': 'Other', 'category': 'downtime', 'creates_timer': True, 'display_order': 99},
    {'code': 'WORK_COMPLETE', 'name': 'Work Complete', 'category': 'complete', 'creates_timer': False, 'display_order': 100},
]

for r in reasons:
    DowntimeReason.objects.get_or_create(code=r['code'], defaults=r)
```

### 3. Update URL Configuration
Add the new endpoint to your URLs:
```python
# In tasks/urls.py or wherever timer routes are defined
from tasks.views import DowntimeReasonListView

urlpatterns = [
    # ... existing patterns ...
    path('downtime-reasons/', DowntimeReasonListView.as_view(), name='downtime-reasons-list'),
]
```

## Frontend Integration Guide

### 1. Fetch Downtime Reasons on App Load
```javascript
const reasons = await fetch('/api/tasks/downtime-reasons/').then(r => r.json());
// Store in app state for use when stopping timers
```

### 2. Stopping Timer with Reason (Unified Workflow)
Show modal with reason buttons and comment field:
```javascript
// User clicks "Stop Timer" OR "Log Reason" (when no active timer)
showReasonModal({
  reasons: downtimeReasons,
  currentTimer: activeTimer,  // null if no active timer
  onSubmit: async (reasonId, comment) => {
    const payload = {
      reason_id: reasonId,
      comment: comment,
    };

    // If there's an active timer, include it
    if (activeTimer) {
      payload.current_timer_id = activeTimer.id;
    } else {
      // No active timer - user is just logging a reason
      payload.machine_id = selectedMachine.id;
      payload.operation_key = selectedOperation.key;
    }

    const response = await fetch('/api/tasks/log-reason/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(r => r.json());

    // Handle response
    if (response.timer) {
      // New timer created - use full timer object
      updateUIWithNewTimer(response.timer);

      // Check if it's a fault-related timer
      if (response.timer.related_fault_id) {
        showWarning("This timer will stop automatically when the fault is resolved");
      }
    }
    if (response.fault_id) {
      // Machine fault reported
      showNotification(`Fault reported: #${response.fault_id}`);
    }
    if (response.operation_completed) {
      // Operation was marked complete
      markOperationComplete();
      showSuccess("Operation completed!");
    }

    showMessage(response.message);
  }
});
```

### 3. Preventing Manual Stop of Fault-Related Timers
```javascript
// Check if timer can be stopped by user
if (timer.related_fault_id !== null) {
  // Show disabled stop button with tooltip
  showTooltip("Timer will stop automatically when fault is resolved");
  disableStopButton();
} else if (!timer.can_be_stopped_by_user) {
  // Additional check from backend
  showTooltip("Cannot manually stop this timer");
  disableStopButton();
}
```

### 4. Visual Distinction
Use different colors/icons for timer types:
- Productive: Green / 🟢
- Break/Lunch: Blue / 🔵
- Downtime: Amber/Red / 🟡
- Fault-related: Red with lock icon / 🔴🔒 (cannot be stopped manually)

### 5. Reporting
Filter timers by type for analysis:
```javascript
// Get all productive time
const productiveTimers = allTimers.filter(t => t.timer_type === 'productive');

// Get downtime by reason
const waitingMaterials = allTimers.filter(t =>
  t.timer_type === 'downtime' && t.downtime_reason_code === 'WAITING_MATERIALS'
);

// Get fault-related downtime
const faultDowntime = allTimers.filter(t =>
  t.timer_type === 'downtime' && t.related_fault_id !== null
);
```

## Reporting & Analytics

### Time Breakdown by Type
```sql
SELECT
  timer_type,
  COUNT(*) as count,
  SUM(finish_time - start_time) / 3600000.0 as total_hours
FROM tasks_timer
WHERE finish_time IS NOT NULL
GROUP BY timer_type;
```

### Downtime by Reason
```sql
SELECT
  dr.name,
  dr.category,
  COUNT(*) as count,
  SUM(t.finish_time - t.start_time) / 3600000.0 as total_hours
FROM tasks_timer t
JOIN tasks_downtimereason dr ON t.downtime_reason_id = dr.id
WHERE t.timer_type = 'downtime' AND t.finish_time IS NOT NULL
GROUP BY dr.name, dr.category
ORDER BY total_hours DESC;
```

### Machine Fault Impact
```sql
SELECT
  mf.id,
  mf.description,
  COUNT(t.id) as affected_timers,
  SUM(t.finish_time - t.start_time) / 3600000.0 as downtime_hours
FROM machines_machinefault mf
JOIN tasks_timer t ON t.related_fault_id = mf.id
WHERE t.timer_type = 'downtime'
GROUP BY mf.id, mf.description
ORDER BY downtime_hours DESC;
```

### Machine Utilization & Downtime
```sql
-- Machine downtime by fault
SELECT
  m.name as machine_name,
  mf.description,
  mf.reported_at,
  mf.resolved_at,
  (mf.downtime_end_ms - mf.downtime_start_ms) / 3600000.0 as machine_downtime_hours,
  COUNT(dt.id) as operators_affected
FROM machines_machinefault mf
JOIN machines_machine m ON mf.machine_id = m.id
LEFT JOIN tasks_timer dt ON dt.related_fault_id = mf.id AND dt.timer_type = 'downtime'
WHERE mf.is_breaking = true AND mf.downtime_start_ms IS NOT NULL
GROUP BY m.name, mf.id, mf.description, mf.reported_at, mf.resolved_at, mf.downtime_start_ms, mf.downtime_end_ms
ORDER BY machine_downtime_hours DESC;
```

### Machine Availability Rate
```sql
-- Calculate machine availability percentage over a time period
-- (Total Time - Downtime) / Total Time * 100
SELECT
  m.name,
  COUNT(mf.id) as fault_count,
  SUM((mf.downtime_end_ms - mf.downtime_start_ms) / 3600000.0) as total_downtime_hours,
  -- Assuming 24/7 operation, adjust as needed
  ((@period_hours - SUM((mf.downtime_end_ms - mf.downtime_start_ms) / 3600000.0)) / @period_hours * 100) as availability_percentage
FROM machines_machine m
LEFT JOIN machines_machinefault mf ON mf.machine_id = m.id
  AND mf.is_breaking = true
  AND mf.downtime_start_ms >= @start_ms
  AND mf.downtime_end_ms <= @end_ms
GROUP BY m.id, m.name
ORDER BY availability_percentage ASC;
```

## Benefits

1. **Complete Time Accounting**: Minimize blank time by tracking all activities
2. **Root Cause Analysis**: See exactly why production is delayed (materials, tools, faults, etc.)
3. **Automatic Fault Handling**: No manual timer management when machines break
4. **Simple Operator Experience**: 1-2 taps when stopping timers
5. **Backward Compatible**: All existing timers preserved as productive timers
6. **Flexible**: Easy to add new downtime reasons as needs evolve
7. **Rich Reporting**: Clear breakdown of productive vs. non-productive time

## Files Modified

### Models
- `tasks/models.py`: Added `DowntimeReason` model and updated `Timer` model with new fields (`timer_type`, `downtime_reason`, `related_fault`, `can_be_stopped_by_user` property)
- `machines/models.py`: Added machine-level downtime tracking fields to `MachineFault` (`downtime_start_ms`, `downtime_end_ms`, `downtime_hours` property)

### Serializers
- `tasks/serializers.py`: Added `DowntimeReasonSerializer` and updated `BaseTimerSerializer` with new fields
- `machines/serializers.py`: Updated `MachineFaultSerializer` to include `downtime_hours` field

### Views
- `tasks/views.py`:
  - Added `DowntimeReasonListView` for fetching available reasons
  - Added `LogReasonView` - unified endpoint for logging reasons (with or without active timer)
  - Updated `GenericTimerStopView` to prevent stopping fault-related timers
- `machines/views.py`:
  - Updated `MachineFaultListCreateView` to auto-create downtime timers and track machine-level downtime
  - Updated `MachineFaultDetailView` to auto-stop downtime timers and complete machine-level downtime tracking

### URLs
- `tasks/urls.py`: Added routes for `downtime-reasons` and `log-reason` endpoints

### Migrations
- `tasks/migrations/populate_downtime_reasons.py`: Data migration to populate default reasons (requires dependency update)

### Documentation
- `DOWNTIME_TRACKING_IMPLEMENTATION.md`: This comprehensive implementation guide

## Next Steps

1. **Run migrations** to create database tables:
   ```bash
   python manage.py makemigrations tasks machines
   python manage.py migrate
   ```

2. **Update data migration dependency** in `tasks/migrations/populate_downtime_reasons.py`:
   - Replace `XXXX_add_downtime_tracking` with the actual migration number
   - Then run: `python manage.py migrate tasks`

3. **Test the API endpoints**:
   - GET `/tasks/downtime-reasons/` - Fetch available reasons
   - POST `/tasks/log-reason/` - Test unified workflow (with and without active timer)
   - Verify fault-related timers cannot be manually stopped

4. **Update frontend**:
   - Add "Log Reason" button visible even when no active timer
   - Show reason modal with comment field when stopping timers
   - Disable stop button for timers where `can_be_stopped_by_user` is false
   - Handle fault-related timers with visual distinction (lock icon)
   - Display new timer fields (`timer_type`, `downtime_reason_name`, etc.)

5. **Add reporting/dashboard**:
   - Time breakdown by timer type (productive/break/downtime)
   - Downtime analysis by reason
   - Machine utilization and availability rates
   - Fault impact analysis (affected operators, downtime hours)

6. **Train operators** on new workflow:
   - How to log reasons when stopping timers
   - How to report machine faults
   - Understanding that fault-related timers auto-stop when resolved
