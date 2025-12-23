# Welding Time Entry API Documentation

## Overview

The Welding Time Entry system provides manual time tracking for welding employees. Unlike the automated timer system used for machining and CNC cutting, this system allows manual entry of hours worked on specific jobs for specific dates.

### Overtime Types

The system supports three types of work hours:

1. **Regular Hours** (`regular`) - Normal work hours (1.0x multiplier)
2. **After Hours / Saturday** (`after_hours`) - Weekday evenings and Saturdays (1.5x multiplier)
3. **Holiday / Sunday** (`holiday`) - Sundays and holidays (2.0x multiplier)

Employees can have multiple entries for the same job on the same day, including duplicate entries with the same overtime type. This allows flexible tracking of work periods throughout the day.

## Base URL

All welding endpoints are prefixed with: `/welding/`

## Authentication

All endpoints require authentication via JWT token. Include the token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

## Permissions

- **IsWeldingUserOrAdmin**: Grants access to superusers, admin users (office location), users in the 'welding' team, and office workers.

---

## Endpoints

### 1. List Time Entries

**GET** `/welding/time-entries/`

Retrieve a paginated list of welding time entries with filtering and sorting options.

#### Query Parameters

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `employee` | integer | Filter by employee ID | `?employee=5` |
| `employee_username` | string | Filter by employee username (partial match) | `?employee_username=john` |
| `job_no` | string | Filter by job number (partial match) | `?job_no=001` |
| `date` | date | Filter by exact date | `?date=2025-12-20` |
| `date_after` | date | Filter entries on or after this date | `?date_after=2025-12-01` |
| `date_before` | date | Filter entries on or before this date | `?date_before=2025-12-31` |
| `hours_min` | decimal | Filter entries with hours >= value | `?hours_min=4.0` |
| `hours_max` | decimal | Filter entries with hours <= value | `?hours_max=8.0` |
| `overtime_type` | string | Filter by overtime type (`regular`, `after_hours`, `holiday`) | `?overtime_type=after_hours` |
| `description` | string | Filter by description (partial match) | `?description=welding` |
| `ordering` | string | Sort results (prefix with `-` for descending) | `?ordering=-date` |
| `page` | integer | Page number | `?page=2` |
| `page_size` | integer | Items per page (max 100) | `?page_size=50` |

#### Response

```json
{
  "count": 45,
  "next": "http://api.example.com/welding/time-entries/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "employee": 5,
      "employee_username": "john.doe",
      "employee_full_name": "John Doe",
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": "8.00",
      "overtime_type": "regular",
      "overtime_type_display": "Regular Hours",
      "overtime_multiplier": 1.0,
      "description": "Welding main frame structure",
      "created_at": "2025-12-20T10:30:00Z",
      "created_by": 1,
      "created_by_username": "admin",
      "updated_at": "2025-12-20T10:30:00Z",
      "updated_by": null,
      "updated_by_username": null
    }
  ]
}
```

---

### 2. Create Time Entry

**POST** `/welding/time-entries/`

Create a new welding time entry.

#### Request Body

```json
{
  "employee": 5,
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": 8.00,
  "overtime_type": "regular",
  "description": "Welding main frame structure"
}
```

#### Required Fields
- `employee` (integer): Employee user ID
- `job_no` (string): Job number
- `date` (date): Date of work in YYYY-MM-DD format
- `hours` (decimal): Hours worked (must be > 0 and <= 24)

#### Optional Fields
- `overtime_type` (string): Type of hours - `regular` (default), `after_hours`, or `holiday`
- `description` (string): Notes about the work performed

#### Validation Rules
- Hours must be greater than 0 and not exceed 24
- Cannot create entries for inactive employees
- Duplicate entries are allowed - you can create multiple entries with the same employee, job_no, date, and overtime_type

#### Response (201 Created)

```json
{
  "id": 1,
  "employee": 5,
  "employee_username": "john.doe",
  "employee_full_name": "John Doe",
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": "8.00",
  "overtime_type": "regular",
  "overtime_type_display": "Regular Hours",
  "overtime_multiplier": 1.0,
  "description": "Welding main frame structure",
  "created_at": "2025-12-20T10:30:00Z",
  "created_by": 1,
  "created_by_username": "admin",
  "updated_at": "2025-12-20T10:30:00Z",
  "updated_by": null,
  "updated_by_username": null
}
```

#### Error Response (400 Bad Request)

```json
{
  "hours": ["Hours must be greater than 0"],
  "employee": ["Cannot create time entry for inactive employee: john.doe. If this employee has returned to work, please reactivate their account first."]
}
```

---

### 3. Retrieve Time Entry

**GET** `/welding/time-entries/{id}/`

Retrieve details of a specific time entry.

#### Response

```json
{
  "id": 1,
  "employee": 5,
  "employee_username": "john.doe",
  "employee_full_name": "John Doe",
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": "8.00",
  "description": "Welding main frame structure",
  "created_at": "2025-12-20T10:30:00Z",
  "created_by": 1,
  "created_by_username": "admin",
  "updated_at": "2025-12-20T10:30:00Z",
  "updated_by": null,
  "updated_by_username": null
}
```

---

### 4. Update Time Entry

**PUT/PATCH** `/welding/time-entries/{id}/`

Update an existing time entry.

#### Request Body (PATCH - partial update)

```json
{
  "hours": 7.5,
  "description": "Updated: Welding main frame structure"
}
```

#### Response (200 OK)

```json
{
  "id": 1,
  "employee": 5,
  "employee_username": "john.doe",
  "employee_full_name": "John Doe",
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": "7.50",
  "description": "Updated: Welding main frame structure",
  "created_at": "2025-12-20T10:30:00Z",
  "created_by": 1,
  "created_by_username": "admin",
  "updated_at": "2025-12-20T14:30:00Z",
  "updated_by": 1,
  "updated_by_username": "admin"
}
```

---

### 5. Delete Time Entry

**DELETE** `/welding/time-entries/{id}/`

Delete a time entry.

#### Response (204 No Content)

No response body.

---

### 6. Bulk Create Time Entries

**POST** `/welding/time-entries/bulk-create/`

Create multiple time entries in a single transaction.

#### Request Body

```json
{
  "entries": [
    {
      "employee": 5,
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": 8.0,
      "description": "Welding main frame"
    },
    {
      "employee": 5,
      "job_no": "002-23",
      "date": "2025-12-20",
      "hours": 2.0,
      "description": "Welding support structure"
    },
    {
      "employee": 6,
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": 7.5,
      "description": "Welding joints"
    }
  ]
}
```

#### Validation
- All entries must pass validation (hours > 0 and <= 24, no inactive employees)
- Duplicate entries are allowed
- If any entry fails validation, the entire transaction is rolled back (all-or-nothing)

#### Response (201 Created)

```json
{
  "created_count": 3,
  "entries": [
    {
      "id": 1,
      "employee": 5,
      "employee_username": "john.doe",
      "employee_full_name": "John Doe",
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": "8.00",
      "description": "Welding main frame",
      "created_at": "2025-12-20T10:30:00Z",
      "created_by": 1,
      "created_by_username": "admin",
      "updated_at": "2025-12-20T10:30:00Z",
      "updated_by": null,
      "updated_by_username": null
    },
    {
      "id": 2,
      "employee": 5,
      "employee_username": "john.doe",
      "employee_full_name": "John Doe",
      "job_no": "002-23",
      "date": "2025-12-20",
      "hours": "2.00",
      "description": "Welding support structure",
      "created_at": "2025-12-20T10:30:00Z",
      "created_by": 1,
      "created_by_username": "admin",
      "updated_at": "2025-12-20T10:30:00Z",
      "updated_by": null,
      "updated_by_username": null
    },
    {
      "id": 3,
      "employee": 6,
      "employee_username": "jane.smith",
      "employee_full_name": "Jane Smith",
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": "7.50",
      "description": "Welding joints",
      "created_at": "2025-12-20T10:30:00Z",
      "created_by": 1,
      "created_by_username": "admin",
      "updated_at": "2025-12-20T10:30:00Z",
      "updated_by": null,
      "updated_by_username": null
    }
  ]
}
```

#### Error Response (400 Bad Request)

```json
{
  "entries": [
    "At least one entry is required"
  ]
}
```

---

### 7. Get Job Hours Report

**GET** `/welding/time-entries/job-hours/`

Get aggregated hours for a specific job with breakdown by employee and date.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `job_no` | string | Yes | Job number to search (supports partial match) |
| `date_after` | date | No | Filter entries on or after this date |
| `date_before` | date | No | Filter entries on or before this date |

#### Example Request

```
GET /welding/time-entries/job-hours/?job_no=001-23&date_after=2025-12-01&date_before=2025-12-31
```

#### Response

```json
{
  "job_no": "001-23",
  "total_hours": 45.5,
  "entry_count": 12,
  "breakdown_by_employee": [
    {
      "employee_id": 5,
      "employee_username": "john.doe",
      "employee_full_name": "John Doe",
      "hours": 28.0,
      "entry_count": 7
    },
    {
      "employee_id": 6,
      "employee_username": "jane.smith",
      "employee_full_name": "Jane Smith",
      "hours": 17.5,
      "entry_count": 5
    }
  ],
  "breakdown_by_date": [
    {
      "date": "2025-12-20",
      "hours": 15.5,
      "entry_count": 3
    },
    {
      "date": "2025-12-19",
      "hours": 16.0,
      "entry_count": 4
    },
    {
      "date": "2025-12-18",
      "hours": 14.0,
      "entry_count": 5
    }
  ]
}
```

---

## Common Use Cases

### Example 1: Get all entries for a specific employee in December 2025

```
GET /welding/time-entries/?employee=5&date_after=2025-12-01&date_before=2025-12-31&ordering=-date
```

### Example 2: Find all entries for jobs starting with "001"

```
GET /welding/time-entries/?job_no=001&ordering=-date
```

### Example 3: Get total hours for a specific job

```
GET /welding/time-entries/job-hours/?job_no=001-23
```

### Example 4: Bulk insert daily entries for multiple employees

```json
POST /welding/time-entries/bulk-create/
{
  "entries": [
    {
      "employee": 5,
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": 4.0,
      "overtime_type": "regular"
    },
    {
      "employee": 5,
      "job_no": "002-23",
      "date": "2025-12-20",
      "hours": 4.5,
      "overtime_type": "regular"
    },
    {
      "employee": 6,
      "job_no": "001-23",
      "date": "2025-12-20",
      "hours": 8.0,
      "overtime_type": "regular"
    }
  ]
}
```

### Example 5: Get only overtime entries (after hours)

```
GET /welding/time-entries/?overtime_type=after_hours&ordering=-date
```

### Example 6: Create entry with regular and overtime hours for same employee/job/day

```json
// First entry - regular hours
POST /welding/time-entries/
{
  "employee": 5,
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": 8.0,
  "overtime_type": "regular",
  "description": "Regular shift"
}

// Second entry - overtime hours (allowed because different overtime_type)
POST /welding/time-entries/
{
  "employee": 5,
  "job_no": "001-23",
  "date": "2025-12-20",
  "hours": 2.0,
  "overtime_type": "after_hours",
  "description": "Stayed late to finish"
}
```

---

## Database Schema

### WeldingTimeEntry Table

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | AutoField | PRIMARY KEY | Auto-incrementing ID |
| employee_id | ForeignKey | NOT NULL, INDEXED | Reference to User |
| job_no | CharField(100) | NOT NULL, INDEXED | Job number |
| date | DateField | NOT NULL, INDEXED | Work date |
| hours | Decimal(5,2) | NOT NULL | Hours worked |
| overtime_type | CharField(20) | NOT NULL, INDEXED | Overtime type (regular/after_hours/holiday) |
| description | TextField | NULLABLE | Work description |
| created_at | DateTimeField | AUTO | Creation timestamp |
| created_by_id | ForeignKey | NULLABLE | User who created entry |
| updated_at | DateTimeField | AUTO | Last update timestamp |
| updated_by_id | ForeignKey | NULLABLE | User who last updated |

#### Indexes
- `employee_id, date`
- `job_no, date`
- `date`
- `overtime_type`
- `employee_id` (implicit FK index)
- `job_no` (explicit index)

#### Constraints
- None - Duplicate entries are allowed for flexibility in tracking work periods

---

## Error Codes

| HTTP Code | Description |
|-----------|-------------|
| 200 | Success |
| 201 | Created successfully |
| 204 | Deleted successfully |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (missing or invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 500 | Internal server error |

---

## Notes

1. **Partial Matching**: The `job_no` filter supports partial matching using `icontains`, so searching for "001" will match "001-23", "TI-001", etc.

2. **Duplicate Entries Allowed**: The system allows duplicate entries for the same employee/job/date/overtime_type combination. This provides flexibility for tracking multiple work periods throughout the day on the same job.

3. **Overtime Types**:
   - **regular** (1.0x): Normal work hours
   - **after_hours** (1.5x): Weekday evenings and Saturdays - paid at 1.5x rate
   - **holiday** (2.0x): Sundays and holidays - paid at 2x rate

4. **Multiple Entries Per Day**: An employee can have multiple time entries for the same job on the same day, including duplicate entries with the same overtime type. For example:
   - 4 hours regular (07:00-11:00) - first work period
   - 4 hours regular (13:00-17:00) - second work period after lunch
   - 2 hours after_hours (17:00-19:00) - overtime

   This allows flexible tracking of work periods throughout the day.

5. **Audit Trail**: All entries track who created and last updated them, with automatic timestamps.

6. **Bulk Operations**: Use bulk create for importing daily timesheet data efficiently. The operation is atomic - either all entries are created or none.

7. **Hours Validation**: Hours must be between 0 (exclusive) and 24 (inclusive) per entry.

8. **Timezone**: All timestamps are in UTC. The `date` field represents the work date in the local timezone (configured as Europe/Istanbul in your app settings).

9. **Overtime Multiplier**: Each entry includes an `overtime_multiplier` field (read-only) showing the pay multiplier for that entry type (1.0, 1.5, or 2.0).
