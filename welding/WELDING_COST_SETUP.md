# Welding Cost Calculation Setup Guide

This guide explains how to set up and use the welding cost calculation system.

## Overview

The welding cost calculation system works similarly to the machining system:
1. **WeldingTimeEntry** records are created/updated/deleted
2. Signal handlers automatically enqueue the job_no for recalculation
3. A background process drains the queue and recalculates costs
4. Pre-calculated costs are stored in **WeldingJobCostAgg** and **WeldingJobCostAggUser** tables
5. API endpoints read from these pre-calculated tables for fast performance

## Initial Setup

### 1. Run Migrations

First, ensure the database tables are created:

```bash
python manage.py migrate welding
```

This creates:
- `welding_job_cost_agg` - Job-level cost aggregations
- `welding_job_cost_agg_user` - Per-user cost aggregations
- `welding_job_cost_recalc_queue` - Queue for jobs needing recalculation

### 2. Initial Population

To calculate costs for all existing welding time entries:

```bash
# Option 1: Direct calculation (recommended for initial setup)
python manage.py recompute_welding_job_costs

# Option 2: Enqueue all jobs, then drain the queue
python manage.py enqueue_welding_job_costs
python manage.py drain_welding_cost_queue
```

**Progress tracking:**
The `recompute_welding_job_costs` command shows progress every 10 jobs:
```
Found 250 distinct job_nos to process...
Processed 10/250...
Processed 20/250...
...
Completed! Processed: 250, Failed: 0, Total: 250
```

### 3. Set Up Scheduled Task

Choose one of the following options to automatically process the cost queue:

#### Option A: Cron Job (Recommended for production)

Add to your crontab:
```bash
# Process welding cost queue every 5 minutes
*/5 * * * * cd /path/to/gemkom-backend && python manage.py drain_welding_cost_queue
```

#### Option B: Django Management Command (Manual)

Run manually when needed:
```bash
python manage.py drain_welding_cost_queue --batch=100
```

#### Option C: API Endpoint (For remote triggers)

POST to the internal endpoint:
```bash
curl -X POST http://your-domain/welding/internal/drain-welding-cost-queue/ \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"batch_size": 100}'
```

**Note:** This endpoint requires admin permissions.

## Cost Calculation Details

### How Costs Are Calculated

For each `WeldingTimeEntry`:

1. **Get Employee Wage Rate**
   - Looks up the employee's `WageRate` effective on the entry's date
   - Falls back to system-wide average if employee has no wage rate
   - Uses the TRY currency by default

2. **Calculate Hourly Rate**
   ```python
   base_hourly = base_monthly / 225  # 225 hours per month
   ```

3. **Apply Overtime Multiplier**
   - `regular`: 1.0x (base_hourly × hours)
   - `after_hours`: 1.5x (base_hourly × hours × 1.5)
   - `holiday`: 2.0x (base_hourly × hours × 2.0)

4. **Convert to EUR**
   - Uses historical exchange rates from the date of the entry
   - Looks up TRY → EUR conversion rate

5. **Aggregate by Job**
   - Sums hours and costs per overtime type
   - Stores in `WeldingJobCostAgg` (job-level)
   - Stores in `WeldingJobCostAggUser` (per-user, per-job)

### Example Calculation

```
Employee: John Doe
Date: 2024-01-15
Job: 001-23
Hours: 8.0
Overtime Type: regular
Base Monthly Wage: 45,000 TRY

Calculation:
1. base_hourly = 45,000 / 225 = 200 TRY/hour
2. cost_try = 200 × 8.0 × 1.0 = 1,600 TRY
3. Exchange rate on 2024-01-15: 1 EUR = 32.50 TRY
4. cost_eur = 1,600 / 32.50 = 49.23 EUR
```

## API Endpoints

### 1. Welding Job Cost List
```
GET /welding/reports/job-costs/?job_no=001&ordering=-total_cost
```

Returns aggregated costs per job_no with overtime breakdown.

**Response:**
```json
{
  "count": 1,
  "results": [
    {
      "job_no": "001-23",
      "hours": {
        "regular": 120.0,
        "after_hours": 30.0,
        "holiday": 10.0
      },
      "costs": {
        "regular": 5400.0,
        "after_hours": 2025.0,
        "holiday": 900.0
      },
      "total_cost": 8325.0,
      "currency": "EUR",
      "updated_at": "2024-01-15T12:00:00Z"
    }
  ]
}
```

**Query Parameters:**
- `job_no` - Filter by job number (partial match)
- `ordering` - Sort by: `job_no`, `-job_no`, `total_cost`, `-total_cost`, `updated_at`, `-updated_at`

### 2. Welding Job Cost Detail (Per-User)
```
GET /welding/reports/job-costs/001-23/
GET /welding/reports/job-costs/?job_no=001
```

Returns per-user cost breakdown for a specific job.

**Response:**
```json
{
  "count": 3,
  "results": [
    {
      "user_id": 1,
      "user": "john.doe",
      "hours": {
        "regular": 40.0,
        "after_hours": 10.0,
        "holiday": 0.0
      },
      "costs": {
        "regular": 1800.0,
        "after_hours": 675.0,
        "holiday": 0.0
      },
      "total_cost": 2475.0,
      "currency": "EUR",
      "updated_at": "2024-01-15T12:00:00Z"
    }
  ]
}
```

**Query Parameters:**
- `job_no` - Filter by job number (partial match)
- `ordering` - Sort by: `user`, `-user`, `total_cost`, `-total_cost`, `updated_at`, `-updated_at`

### 3. Combined Job Costs (Machining + Welding)
```
GET /reports/combined-job-costs/?job_no=001&ordering=-combined_total_cost
```

Returns combined costs from both machining and welding departments.

**Response:**
```json
{
  "count": 1,
  "results": [
    {
      "job_no": "001-23",
      "machining": {
        "hours": {
          "weekday_work": 100.0,
          "after_hours": 20.0,
          "sunday": 5.0
        },
        "costs": {
          "weekday_work": 4500.0,
          "after_hours": 900.0,
          "sunday": 450.0
        },
        "total_cost": 5850.0
      },
      "welding": {
        "hours": {
          "regular": 80.0,
          "after_hours": 15.0,
          "holiday": 3.0
        },
        "costs": {
          "regular": 3600.0,
          "after_hours": 1350.0,
          "holiday": 600.0
        },
        "total_cost": 5550.0
      },
      "combined_total_cost": 11400.0,
      "combined_total_hours": 223.0,
      "currency": "EUR",
      "updated_at": "2024-01-15T12:00:00Z"
    }
  ]
}
```

**Query Parameters:**
- `job_no` - Filter by job number (partial match)
- `ordering` - Sort by: `job_no`, `-job_no`, `combined_total_cost`, `-combined_total_cost`, `combined_total_hours`, `-combined_total_hours`

## Management Commands

### `recompute_welding_job_costs`

Immediately recalculates costs for all or specific jobs.

```bash
# Recompute all jobs
python manage.py recompute_welding_job_costs

# Recompute a specific job
python manage.py recompute_welding_job_costs --job-no=001-23
```

**Use cases:**
- Initial population after setup
- Fix data inconsistencies
- Recalculate after wage rate changes

### `enqueue_welding_job_costs`

Enqueues all job_nos for background processing.

```bash
python manage.py enqueue_welding_job_costs
```

**Use cases:**
- Bulk recalculation without blocking
- Prepare jobs for background processing

### `drain_welding_cost_queue`

Processes the recalculation queue in batches.

```bash
# Process with default batch size (100)
python manage.py drain_welding_cost_queue

# Process with custom batch size
python manage.py drain_welding_cost_queue --batch=50
```

**Use cases:**
- Scheduled task (cron/celery)
- Manual queue processing
- Background job processing

## Automatic Recalculation

The system automatically enqueues jobs for recalculation when:

1. **WeldingTimeEntry is created**
   - New time entry → job_no is enqueued

2. **WeldingTimeEntry is updated**
   - Hours changed → job_no is enqueued
   - Employee changed → job_no is enqueued
   - Date changed → job_no is enqueued

3. **WeldingTimeEntry is deleted**
   - Entry removed → job_no is enqueued

The queue is processed by your scheduled task (cron/celery), which runs `drain_welding_cost_queue`.

## Troubleshooting

### Costs Not Showing Up

1. **Check if migrations ran:**
   ```bash
   python manage.py showmigrations welding
   ```

2. **Check if costs were calculated:**
   ```bash
   python manage.py shell
   >>> from welding.models import WeldingJobCostAgg
   >>> WeldingJobCostAgg.objects.count()
   ```

3. **Recalculate manually:**
   ```bash
   python manage.py recompute_welding_job_costs --job-no=YOUR_JOB_NO
   ```

### Queue Not Processing

1. **Check queue size:**
   ```bash
   python manage.py shell
   >>> from welding.models import WeldingJobCostRecalcQueue
   >>> WeldingJobCostRecalcQueue.objects.count()
   ```

2. **Manually drain queue:**
   ```bash
   python manage.py drain_welding_cost_queue
   ```

3. **Check cron/scheduled task is running**

### Incorrect Costs

1. **Verify wage rates exist:**
   ```bash
   python manage.py shell
   >>> from users.models import WageRate
   >>> WageRate.objects.filter(user_id=USER_ID).order_by('-effective_from')
   ```

2. **Check exchange rates:**
   - Costs use historical exchange rates from the entry date
   - Verify rates are available in your currency rate system

3. **Recalculate specific job:**
   ```bash
   python manage.py recompute_welding_job_costs --job-no=YOUR_JOB_NO
   ```

## Performance Considerations

- **Pre-calculated tables** provide fast API responses
- **Queue processing** runs in background, doesn't block user operations
- **Batch processing** prevents memory issues with large datasets
- **Skip locked** allows multiple queue processors to run in parallel

## Next Steps

After initial setup:

1. ✅ Run migrations
2. ✅ Populate initial costs
3. ✅ Set up scheduled task
4. ✅ Verify API endpoints work
5. ✅ Monitor queue processing
6. ✅ Set up monitoring/alerting for failed jobs

The cost calculation system is now fully operational!
