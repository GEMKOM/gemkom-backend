# Welding Time Tracking System

## Overview

This Django app provides manual time entry capabilities for welding employees. Unlike the automated timer system used for machining and CNC cutting operations, this system allows for manual entry of hours worked on specific jobs for specific dates.

## Why Manual Entry?

While machining and CNC cutting operations use an automated timer system where employees start/stop timers as they work, welding operations cannot be tracked this way physically. Therefore, this system allows supervisors or employees to manually enter daily hours worked by job number.

## Key Features

- **CRUD Operations**: Full Create, Read, Update, Delete functionality for time entries
- **Bulk Insert**: Import multiple time entries at once (useful for daily timesheet entry)
- **Job Reporting**: Get aggregated hours for specific jobs with employee and date breakdowns
- **Partial Job Search**: Find all time entries for jobs matching a partial job number
- **Data Integrity**: Prevents duplicate entries (same employee + job + date)
- **Audit Trail**: Tracks who created and modified each entry
- **Flexible Filtering**: Filter by employee, job number, date range, hours, and more

## Architecture

### Models

**WeldingTimeEntry**
- Tracks hours worked by an employee on a specific job for a specific date
- Fields: employee, job_no, date, hours, description
- Audit fields: created_at, created_by, updated_at, updated_by
- Database constraints prevent duplicate entries

### API Endpoints

All endpoints are prefixed with `/welding/`

1. **List/Filter Entries**: `GET /welding/time-entries/`
2. **Create Entry**: `POST /welding/time-entries/`
3. **Retrieve Entry**: `GET /welding/time-entries/{id}/`
4. **Update Entry**: `PUT/PATCH /welding/time-entries/{id}/`
5. **Delete Entry**: `DELETE /welding/time-entries/{id}/`
6. **Bulk Create**: `POST /welding/time-entries/bulk-create/`
7. **Job Hours Report**: `GET /welding/time-entries/job-hours/?job_no=001`

### Permissions

- **IsWeldingUserOrAdmin**: Allows access to:
  - Superusers
  - Admin users (office workers)
  - Users in the 'welding' team
  - All office location users

### Filters

The system supports comprehensive filtering:
- Employee (by ID or username)
- Job number (partial match)
- Date (exact, before, after)
- Hours (min, max)
- Description (partial match)

### Admin Interface

Integrated Django admin panel for managing entries with:
- List display showing key fields
- Search by job number and employee
- Date hierarchy navigation
- Read-only audit fields

## Integration with Existing System

This app follows the same patterns as your existing machining and CNC cutting apps:

1. **Permission System**: Uses the same pattern as `IsMachiningUserOrAdmin` and `IsCuttingUserOrAdmin`
2. **Filtering**: Uses django-filter like your other apps
3. **Pagination**: Uses your custom `CustomPageNumberPagination`
4. **Serializers**: Follows DRF best practices with read-only fields for audit data
5. **URL Routing**: Follows the same structure as machining/cnc_cutting apps

## Differences from Timer-Based Systems

| Feature | Machining/CNC (Automated) | Welding (Manual) |
|---------|---------------------------|------------------|
| Time Tracking | Start/Stop timers | Manual entry of hours |
| Granularity | Millisecond precision | Hours with 2 decimal places |
| Data Model | Timer with start/finish times | Simple hours per day per job |
| Use Case | Real-time tracking | Daily timesheet entry |
| Validation | Active timer checks | Duplicate prevention |

## Database Schema

```sql
CREATE TABLE welding_time_entry (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL REFERENCES auth_user(id),
    job_no VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    hours DECIMAL(5,2) NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by_id BIGINT REFERENCES auth_user(id),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_by_id BIGINT REFERENCES auth_user(id),
    CONSTRAINT unique_welding_time_entry_per_employee_job_date
        UNIQUE (employee_id, job_no, date)
);

CREATE INDEX idx_welding_employee_date ON welding_time_entry(employee_id, date);
CREATE INDEX idx_welding_job_date ON welding_time_entry(job_no, date);
CREATE INDEX idx_welding_date ON welding_time_entry(date);
```

## Installation & Setup

The app has already been:
1. ✅ Created in the `welding/` directory
2. ✅ Added to `INSTALLED_APPS` in `config/settings.py`
3. ✅ URL routes configured in `config/urls.py`

### Next Steps

To complete the setup, you need to:

1. **Create database migrations**:
   ```bash
   python manage.py makemigrations welding
   ```

2. **Apply migrations**:
   ```bash
   python manage.py migrate welding
   ```

3. **Test the API** (see API_DOCUMENTATION.md for examples)

## Files Structure

```
welding/
├── __init__.py
├── admin.py              # Django admin configuration
├── apps.py               # App configuration
├── filters.py            # Django-filter FilterSet
├── models.py             # WeldingTimeEntry model
├── permissions.py        # IsWeldingUserOrAdmin permission
├── serializers.py        # DRF serializers (single + bulk)
├── urls.py               # URL routing
├── views.py              # ViewSet and bulk create view
├── API_DOCUMENTATION.md  # Complete API reference
└── README.md             # This file
```

## Usage Examples

### Create a Single Entry

```bash
curl -X POST http://localhost:8000/welding/time-entries/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "employee": 5,
    "job_no": "001-23",
    "date": "2025-12-20",
    "hours": 8.0,
    "description": "Welding main frame"
  }'
```

### Bulk Create Daily Entries

```bash
curl -X POST http://localhost:8000/welding/time-entries/bulk-create/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [
      {"employee": 5, "job_no": "001-23", "date": "2025-12-20", "hours": 4.0},
      {"employee": 5, "job_no": "002-23", "date": "2025-12-20", "hours": 4.5},
      {"employee": 6, "job_no": "001-23", "date": "2025-12-20", "hours": 8.0}
    ]
  }'
```

### Get Hours for a Job

```bash
curl -X GET "http://localhost:8000/welding/time-entries/job-hours/?job_no=001-23" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Filter Entries

```bash
# Get all entries for employee 5 in December 2025
curl -X GET "http://localhost:8000/welding/time-entries/?employee=5&date_after=2025-12-01&date_before=2025-12-31" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## Future Enhancements

Possible additions for the future:
- Export to Excel/CSV
- Weekly/Monthly summary reports
- Integration with wage calculation (similar to machining job costs)
- Mobile-friendly timesheet entry UI
- Bulk import from spreadsheet
- Approval workflow for time entries

## Support

For detailed API documentation, see [API_DOCUMENTATION.md](./API_DOCUMENTATION.md)
