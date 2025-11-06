# Daily User Report - Example Response

## Endpoint
`GET /machining/reports/daily-user-report/?date=2024-01-15`

## Example Response

```json
{
  "date": "2024-01-15",
  "users": [
    {
      "user_id": 1,
      "username": "john.doe",
      "first_name": "John",
      "last_name": "Doe",
      "tasks": [
        {
          "start_time": 1705312800000,
          "finish_time": 1705316400000,
          "task_key": "TI-001",
          "task_name": "Machine Setup - Job J-100",
          "job_no": "J-100",
          "duration_minutes": 60,
          "estimated_hours": 8.0,
          "total_hours_spent": 3.5,
          "comment": "Initial setup and calibration",
          "machine_name": "Doosan DBC130L II",
          "manual_entry": false
        },
        {
          "start_time": 1705317000000,
          "finish_time": 1705324200000,
          "task_key": "TI-002",
          "task_name": "Production Run - Part A",
          "job_no": "J-100",
          "duration_minutes": 120,
          "estimated_hours": 6.0,
          "total_hours_spent": 4.0,
          "comment": "First batch production",
          "machine_name": "Doosan DBC130L II",
          "manual_entry": false
        },
        {
          "start_time": 1705326000000,
          "finish_time": 1705330800000,
          "task_key": "TI-003",
          "task_name": "Quality Check",
          "job_no": "J-101",
          "duration_minutes": 80,
          "estimated_hours": 2.0,
          "total_hours_spent": 1.33,
          "comment": null,
          "machine_name": null,
          "manual_entry": true
        }
      ],
      "idle_periods": [
        {
          "start_time": 1705311000000,
          "finish_time": 1705312800000,
          "duration_minutes": 30
        },
        {
          "start_time": 1705316400000,
          "finish_time": 1705317000000,
          "duration_minutes": 10
        },
        {
          "start_time": 1705324200000,
          "finish_time": 1705326000000,
          "duration_minutes": 30
        },
        {
          "start_time": 1705330800000,
          "finish_time": 1705335000000,
          "duration_minutes": 70
        }
      ],
      "total_work_hours": 4.33,
      "total_idle_hours": 2.34,
      "total_time_in_office_hours": 6.67
    },
    {
      "user_id": 2,
      "username": "jane.smith",
      "first_name": "Jane",
      "last_name": "Smith",
      "tasks": [
        {
          "start_time": 1705312800000,
          "finish_time": 1705320000000,
          "task_key": "TI-004",
          "task_name": "Material Preparation",
          "job_no": "J-102",
          "duration_minutes": 120,
          "estimated_hours": 4.0,
          "total_hours_spent": 2.5,
          "comment": "Cutting and preparing materials",
          "machine_name": "CNC Router",
          "manual_entry": false
        },
        {
          "start_time": 1705321800000,
          "finish_time": 1705332600000,
          "task_key": "TI-005",
          "task_name": "Assembly Work",
          "job_no": "J-102",
          "duration_minutes": 180,
          "estimated_hours": 5.0,
          "total_hours_spent": 3.0,
          "comment": "Final assembly",
          "machine_name": null,
          "manual_entry": false
        }
      ],
      "idle_periods": [
        {
          "start_time": 1705311000000,
          "finish_time": 1705312800000,
          "duration_minutes": 30
        },
        {
          "start_time": 1705320000000,
          "finish_time": 1705321800000,
          "duration_minutes": 30
        },
        {
          "start_time": 1705332600000,
          "finish_time": 1705335000000,
          "duration_minutes": 40
        }
      ],
      "total_work_hours": 5.0,
      "total_idle_hours": 1.67,
      "total_time_in_office_hours": 6.67
    },
    {
      "user_id": 3,
      "username": "bob.wilson",
      "first_name": "Bob",
      "last_name": "Wilson",
      "tasks": [],
      "idle_periods": [
        {
          "start_time": 1705311000000,
          "finish_time": 1705335000000,
          "duration_minutes": 400
        }
      ],
      "total_work_hours": 0.0,
      "total_idle_hours": 6.67,
      "total_time_in_office_hours": 6.67
    }
  ]
}
```

## Field Descriptions

### Top Level
- `date`: The report date in ISO format (YYYY-MM-DD)

### User Object
- `user_id`: Database ID of the user
- `username`: User's username
- `first_name`: User's first name
- `last_name`: User's last name
- `tasks`: Array of tasks the user worked on during the day
- `idle_periods`: Array of idle time periods (gaps between timers within working hours)
- `total_work_hours`: Total hours spent on tasks (sum of all task durations)
- `total_idle_hours`: Total hours of idle time within working hours
- `total_time_in_office_hours`: Sum of work hours and idle hours

### Task Object
- `start_time`: Timer start time in epoch milliseconds
- `finish_time`: Timer finish time in epoch milliseconds (null if still running)
- `task_key`: Task identifier (e.g., "TI-001")
- `task_name`: Name/description of the task
- `job_no`: Job number associated with the task (can be null)
- `duration_minutes`: Duration of this timer session in minutes (rounded to nearest minute)
- `estimated_hours`: Total estimated hours for the task (from task.estimated_hours, can be null)
- `total_hours_spent`: Total hours spent on this task across all timers (cumulative, rounded to 2 decimals)
- `comment`: Optional comment from the timer
- `machine_name`: Name of the machine used (can be null)
- `manual_entry`: Boolean indicating if this was a manually entered timer

### Idle Period Object
- `start_time`: Start of idle period in epoch milliseconds
- `finish_time`: End of idle period in epoch milliseconds
- `duration_minutes`: Duration in minutes (rounded to nearest minute)

## Notes

1. **Working Hours**: Idle periods are only calculated within working hours (07:30-17:00 on weekdays)
2. **Weekends**: On weekends, `idle_periods` will be empty as there are no working hours
3. **Active Timers**: If a timer is still running (no `finish_time`), it's calculated up to the current time
4. **No Tasks**: If a user has no tasks but was in the office, the entire working day is shown as one idle period
5. **Time Format**: All timestamps are in epoch milliseconds (UTC)

## Example: Weekend Response

For a Saturday or Sunday, the response would look like:

```json
{
  "date": "2024-01-13",
  "users": [
    {
      "user_id": 1,
      "username": "john.doe",
      "first_name": "John",
      "last_name": "Doe",
      "tasks": [
        {
          "start_time": 1705132800000,
          "finish_time": 1705136400000,
          "task_key": "TI-010",
          "task_name": "Weekend Maintenance",
          "job_no": null,
          "duration_minutes": 60,
          "estimated_hours": 2.0,
          "total_hours_spent": 1.0,
          "comment": "Weekend work",
          "machine_name": null,
          "manual_entry": false
        }
      ],
      "idle_periods": [],
      "total_work_hours": 1.0,
      "total_idle_hours": 0.0,
      "total_time_in_office_hours": 1.0
    }
  ]
}
```

Note: `idle_periods` is empty on weekends because working hours are not defined for Saturday/Sunday.

