# Attendance / Check-In-Check-Out System

## Context

The company currently uses SpeedUp (external mobile app) for employee check-in/check-out. It has been unreliable — users get blocked by GPS errors, app issues, etc. The goal is to replace it entirely with an internal web-based attendance system that:

- Works for **white collar** employees via office IP range verification (no friction)
- Works for **blue collar / mobile** employees via browser GPS geofencing (no extra hardware)
- Has a **manual override** path (pending record + HR approval) when GPS fails but worker is genuinely on-site
- Flags **overtime** (can feed into existing `OvertimeEntry`/`WageRate` models)
- Is **admin-configurable** (geofence center/radius set from admin panel)

---

## New Django App: `attendance`

### Models

#### `AttendanceSite`
Company premises configuration (admin-managed, single row expected):
```
name            CharField
latitude        DecimalField(max_digits=9, decimal_places=6)
longitude       DecimalField(max_digits=9, decimal_places=6)
radius_meters   PositiveIntegerField  (default: 150)
allowed_ip_ranges  JSONField  (list of CIDR strings, e.g. ["192.168.1.0/24"])
```

#### `AttendanceRecord`
One row per check-in event:
```
user            ForeignKey(User)
date            DateField  (auto from check_in_time)
check_in_time   DateTimeField
check_out_time  DateTimeField (nullable)
method          CharField choices: ['ip', 'gps', 'manual_override', 'hr_manual']
status          CharField choices: ['active', 'complete', 'pending_override', 'override_rejected']
check_in_lat    DecimalField (nullable, stored for audit)
check_in_lon    DecimalField (nullable)
check_out_lat   DecimalField (nullable)
check_out_lon   DecimalField (nullable)
client_ip       GenericIPAddressField (nullable, stored for audit)
override_reason TextField (nullable — worker's explanation when method=manual_override)
reviewed_by     ForeignKey(User, nullable — HR who approved/rejected override)
reviewed_at     DateTimeField (nullable)
overtime_hours  DecimalField(max_digits=5, decimal_places=2, default=0)
notes           TextField (nullable, HR notes)
created_at      DateTimeField(auto_now_add=True)
```

Constraints:
- Unique together: `(user, date)` — only one record per user per day (prevents double check-in)
- `check_out_time > check_in_time` check constraint

#### `ShiftRule` (simple, no complex scheduling)
Defines expected working hours for overtime calculation:
```
name              CharField
work_location     CharField choices: ['workshop', 'office', 'all']
expected_start    TimeField  (e.g. 08:00)
expected_end      TimeField  (e.g. 17:00)
overtime_threshold_minutes  PositiveIntegerField (default: 30)
is_active         BooleanField
```
HR sets one or two shift rules (workshop, office). Overtime = `check_out - expected_end` if > threshold.

---

### Check-In Flow

#### White Collar (office / IP-based)
1. Frontend sends `POST /attendance/check-in/` with no extra payload
2. Backend extracts client IP (respecting `X-Forwarded-For` from Cloud Run)
3. Checks IP against `AttendanceSite.allowed_ip_ranges`
4. If match → create `AttendanceRecord(method='ip', status='active')`
5. If no match → return 403 with reason `"not_on_office_network"`

#### Blue Collar (mobile / GPS-based)
1. Frontend requests browser geolocation, sends `POST /attendance/check-in/` with `{lat, lon}`
2. Backend computes Haversine distance to `AttendanceSite` center
3. If within radius → create `AttendanceRecord(method='gps', status='active')`
4. If outside radius → return 403 with reason `"outside_geofence"`, distance included in response

#### Manual Override (GPS failed or out of range)
1. Worker submits `POST /attendance/check-in/` with `{override_reason: "...", lat (optional), lon (optional)}`
2. Backend creates `AttendanceRecord(method='manual_override', status='pending_override')`
3. Notification sent to HR group users immediately (using existing `notifications` app pattern)
4. HR sees pending records in their dashboard and can approve → `status='active'`, `reviewed_by`, `reviewed_at` set
5. HR rejects → `status='override_rejected'`, worker is notified

#### HR Manual Entry
HR can create/edit records directly via `POST /attendance/hr/records/` — status set to `'complete'` with `method='hr_manual'`.

---

### Check-Out Flow

`POST /attendance/check-out/` — finds today's `active` record for the user, sets `check_out_time`, computes `overtime_hours` based on active `ShiftRule`, sets `status='complete'`.

GPS/IP re-verification on check-out: same logic applies (optional — can be soft-warn only on checkout since hard block at checkout is less useful).

---

### Overtime Calculation

On check-out:
1. Find matching `ShiftRule` (by `user.userprofile.work_location`)
2. `worked_minutes = (check_out_time - check_in_time).total_seconds() / 60`
3. `expected_minutes = (expected_end - expected_start) in minutes`
4. If `worked_minutes - expected_minutes > overtime_threshold_minutes`:
   - `overtime_hours = (worked_minutes - expected_minutes) / 60`
   - Store on `AttendanceRecord.overtime_hours`
5. Future integration with existing `OvertimeEntry` (overtime app) is possible but out of scope for this phase — we flag it here, HR decides whether to formally submit an OvertimeRequest.

---

### API Endpoints

```
POST   /attendance/check-in/              — employee check-in (ip/gps/override)
POST   /attendance/check-out/             — employee check-out
GET    /attendance/today/                 — current user's record for today
GET    /attendance/history/               — current user's history (paginated)

# HR endpoints (permission: HR group)
GET    /attendance/hr/records/            — all records, filterable by date/user/status
POST   /attendance/hr/records/            — manual HR entry
PATCH  /attendance/hr/records/{id}/       — edit any record
POST   /attendance/hr/records/{id}/approve-override/  — approve pending override
POST   /attendance/hr/records/{id}/reject-override/   — reject pending override
GET    /attendance/hr/pending-overrides/  — shortcut: pending_override records

# Admin config
GET/PUT /attendance/hr/site/             — get/update AttendanceSite config
GET    /attendance/hr/shift-rules/       — list shift rules
POST   /attendance/hr/shift-rules/       — create shift rule
PATCH  /attendance/hr/shift-rules/{id}/  — edit shift rule
```

---

### Permissions

- Add `HR` group (or reuse existing group structure) with permission to access `/attendance/hr/*`
- Employee self-service endpoints require only authentication
- `IsHROrAdmin` permission class (check `request.user.groups.filter(name='HR')`)

---

### Frontend Considerations (to communicate to frontend team)

- Check-in button should call `navigator.geolocation.getCurrentPosition()` for blue collar workers
- For office workers, just POST — backend determines method from IP match
- Display check-in status clearly: "Checked in at 08:03 (GPS)" or "Pending HR approval"
- Override form: text area for reason, optional GPS attempt
- HR dashboard needs a "Pending Overrides" badge/notification

---

## Critical Files to Create/Modify

| File | Action |
|------|--------|
| `attendance/models.py` | Create — `AttendanceSite`, `AttendanceRecord`, `ShiftRule` |
| `attendance/views.py` | Create — check-in/out, history, HR endpoints |
| `attendance/serializers.py` | Create |
| `attendance/services.py` | Create — IP check, haversine distance, overtime calc |
| `attendance/urls.py` | Create |
| `attendance/permissions.py` | Create — `IsHROrAdmin` |
| `attendance/migrations/` | Create via makemigrations |
| `config/settings.py` | Add `attendance` to INSTALLED_APPS |
| `config/urls.py` | Add `path('attendance/', include('attendance.urls'))` |
| `notifications/` | Reuse existing notification service for override alerts |

---

## Reusable Existing Code

- `notifications` app — for sending HR notifications on override requests (check `notifications/services.py` pattern)
- `approvals/services.py` — NOT used here (override approval is simpler: direct HR action, no multi-stage workflow needed)
- `overtime/models.py` — `OvertimeEntry` exists; we store `overtime_hours` on `AttendanceRecord` now, with a clear migration path to create `OvertimeEntry` rows later
- `users/models.py` `UserProfile.work_location` — used to select the correct `ShiftRule`

---

## Verification / Testing

1. Create `AttendanceSite` row with real company coordinates + office IP CIDR
2. Create two `ShiftRule` rows (workshop 08:00–17:00, office 08:30–17:30)
3. Test check-in from office network → expect `method='ip'`
4. Test check-in from mobile with coordinates inside radius → expect `method='gps'`
5. Test check-in from outside radius → expect 403 with `outside_geofence`
6. Test override request → expect `status='pending_override'` and HR notification created
7. HR approves override → expect `status='active'`
8. Check-out after 9.5h shift → expect `overtime_hours > 0`
9. Double check-in on same day → expect 409 Conflict
10. HR manual entry → expect `method='hr_manual'`, `status='complete'`
