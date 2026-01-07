# Night Migration: Machining Tasks → Parts/Operations

## ⚠️ CRITICAL: Read Before Starting

**This migration will:**
- ✅ Copy all machining Tasks → new Parts + Operations
- ✅ Move all Timers to point to new Operations
- ✅ Copy all cost data to new PartCost tables
- ❌ **NOT delete** any machining tables (safe rollback possible)

**Prerequisites:**
- No active timers running (verify first!)
- Database backup completed
- Application services stopped
- Estimated time: 30-60 minutes for ~10,000 tasks

---

## Step-by-Step Execution

### BEFORE YOU START (30 mins before migration)

```bash
# 1. Announce to users - stop using the system
# Send email/Slack notification

# 2. Wait for all active timers to be stopped
# Monitor until this returns 0:
psql -d your_database -c "SELECT COUNT(*) FROM tasks_timer WHERE finish_time IS NULL;"
```

### PHASE 1: Preparation (10 minutes)

```bash
# 1. Stop application
sudo systemctl stop gunicorn  # or your app service
sudo systemctl stop celery    # if you have background workers

# 2. Verify no active connections
psql -d your_database -c "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'your_database';"

# 3. Backup database (CRITICAL!)
pg_dump your_database > backup_migration_$(date +%Y%m%d_%H%M%S).sql

# 4. Verify backup
ls -lh backup_migration_*.sql  # Should show file size

# 5. Navigate to project directory
cd /path/to/gemkom-backend
source venv/bin/activate  # or your virtual environment
```

### PHASE 2: Run Migrations (5 minutes)

```bash
# 1. Create database migrations for new models
python manage.py makemigrations tasks

# Expected output:
#   Migrations for 'tasks':
#     tasks/migrations/0006_....py
#       - Add field task_key to part
#       - Create model PartCostAgg
#       - Create model PartCostAggUser
#       - Create model PartCostRecalcQueue

# 2. Apply migrations
python manage.py migrate

# 3. Verify new tables exist
psql -d your_database -c "\dt tasks_partcost*"
# Should show:
#   tasks_partcostagg
#   tasks_partcostaguser
#   tasks_partcostrecalcqueue
```

### PHASE 3: Dry Run (5 minutes)

```bash
# Test migration without making changes
python manage.py migrate_tasks_to_parts --dry-run --limit 10

# Review output - should show:
#   [DRY RUN] Would migrate M-001 → Part: PT-M-001, Operation: M-001
#   ...

# If errors appear, STOP and investigate!
```

### PHASE 4: Execute Migration (15-30 minutes)

```bash
# 1. Migrate all tasks to parts/operations
python manage.py migrate_tasks_to_parts

# Monitor output - should show progress every 100 tasks
# Example output:
#   Found 5234 tasks to migrate
#   ✓ Migrated M-001 → Part: PT-M-001, Operation: M-001
#   ...
#   Progress: 1000/5234 migrated, 0 skipped...
#   ...
#   MIGRATION COMPLETE
#   Total tasks: 5234
#   Migrated:    5234
#   Skipped:     0
#   Failed:      0

# 2. If any failures, check the error messages
# Common issues:
#   - Duplicate keys: Task key already exists as operation
#   - Missing references: created_by user doesn't exist
#   - Fix manually or skip failed tasks

# 3. Migrate cost data
python manage.py migrate_job_costs

# Output:
#   Migrating JobCostAgg → PartCostAgg...
#   Found 4532 JobCostAgg records
#   ✓ Migrated cost for M-001 → PT-M-001
#   ...
#   JobCostAgg: Migrated 4532, Skipped 0, Failed 0
#
#   Migrating JobCostAggUser → PartCostAggUser...
#   Found 15234 JobCostAggUser records
#   ...
#   JobCostAggUser: Migrated 15234, Skipped 0, Failed 0
```

### PHASE 5: Validation (5 minutes)

```bash
# Run validation to ensure migration succeeded
python manage.py validate_migration

# Expected output:
#   ============================================================
#   MIGRATION VALIDATION
#   ============================================================
#
#   1. Checking Tasks → Parts migration...
#      Tasks:  5234
#      Parts:  5234
#      ✓ All tasks migrated to parts
#
#   2. Checking Operations creation...
#      Operations: 5234
#      ✓ All parts have operations
#
#   3. Checking Part→Operation relationship...
#      ✓ All parts have exactly 1 operation
#
#   4. Checking Timer migration...
#      Timers on operations: 25432
#      ✓ No timers pointing to old tasks
#
#   5. Checking Cost data migration...
#      JobCostAgg:  4532
#      PartCostAgg: 4532
#      ✓ All costs migrated
#
#   6. Checking Per-user cost migration...
#      JobCostAggUser:  15234
#      PartCostAggUser: 15234
#      ✓ All user costs migrated
#
#   7. Spot checking data integrity...
#      ✓ Spot check passed
#
#   ============================================================
#   VALIDATION PASSED
#   ============================================================

# IF VALIDATION FAILS:
# - Review error messages
# - Check database manually
# - Consider rollback (see below)
```

### PHASE 6: Recompute Costs (Optional, 10-20 minutes)

```bash
# Optionally recompute all costs from scratch to verify
# This reads timers and recalculates - good final check
python manage.py recompute_part_costs --workers 4

# Progress output:
#   Starting cost recomputation with 4 worker(s)...
#   Progress: 50 parts processed...
#   Progress: 100 parts processed...
#   ...
#   RECOMPUTATION COMPLETE
#   Successful: 5234
#   Failed:     0
```

### PHASE 7: Restart Application (5 minutes)

```bash
# 1. Start application services
sudo systemctl start gunicorn
sudo systemctl start celery  # if applicable

# 2. Check logs for errors
sudo journalctl -u gunicorn -f --lines=100

# 3. Monitor for startup errors
# Look for:
#   - Django starting successfully
#   - No database connection errors
#   - No import errors

# 4. Test basic functionality (in browser/Postman)
# - GET /api/parts/ (should return parts)
# - GET /api/operations/ (should return operations)
# - GET /api/operations/?view=operator (operator view)
# - POST /api/operations/{key}/start-timer/ (start a test timer)
# - POST /api/operations/{key}/stop-timer/ (stop the test timer)
```

### PHASE 8: Post-Migration Verification (10 minutes)

```bash
# 1. Check a few parts in database
psql -d your_database

SELECT key, task_key, name, job_no FROM tasks_part LIMIT 5;
#   key      | task_key | name           | job_no
#   PT-M-001 | M-001    | Housing        | J-2024-001
#   PT-M-002 | M-002    | Cover Plate    | J-2024-001
#   ...

# 2. Check operations
SELECT key, part_id, name, machine_fk_id FROM tasks_operation LIMIT 5;
#   key   | part_id   | name           | machine_fk_id
#   M-001 | PT-M-001  | Housing        | 3
#   M-002 | PT-M-002  | Cover Plate    | 5
#   ...

# 3. Check timers point to operations
SELECT content_type_id, object_id, start_time FROM tasks_timer LIMIT 3;
# Verify content_type_id is for Operation model

# 4. Check costs
SELECT part_id, total_cost, hours_ww FROM tasks_partcostagg LIMIT 5;
#   part_id   | total_cost | hours_ww
#   PT-M-001  | 1250.50    | 8.50
#   PT-M-002  | 750.25     | 5.25
#   ...

\q  # exit psql
```

---

## ✅ Success Criteria

Migration is successful when:
- [ ] All tasks migrated to parts (counts match)
- [ ] All operations created (1 per part)
- [ ] No timers pointing to old tasks
- [ ] All cost data migrated
- [ ] Validation command passes
- [ ] Application starts without errors
- [ ] Can view parts/operations in browser
- [ ] Can start/stop timers on operations
- [ ] Cost calculations run successfully

---

## 🔴 Rollback Plan (If Something Goes Wrong)

```bash
# STOP! If migration failed or validation errors:

# 1. Stop application immediately
sudo systemctl stop gunicorn
sudo systemctl stop celery

# 2. Restore database from backup
psql -d your_database < backup_migration_TIMESTAMP.sql

# 3. Restart application
sudo systemctl start gunicorn
sudo systemctl start celery

# 4. Verify old system is working
# Test in browser that old machining views work

# 5. Investigate what went wrong
# - Review migration command output
# - Check error logs
# - Fix issues before retrying
```

---

## 📝 Post-Migration Notes

### What Changed:
- **Frontend**: Should work unchanged (operation keys match old task keys)
- **Timer endpoints**: Now use `/api/operations/{key}/start-timer/`
- **Cost calculations**: Now use Part-based models
- **Planning**: Operations now appear in planning (not tasks)

### Old System Status:
- **machining_task table**: Still exists, not deleted
- **machining_jobcostagg**: Still exists, not deleted
- **Machining signals**: Still active (won't break anything)
- **Machining views**: May show empty/stale data (timers moved)

### When to Delete Old Tables:
- Wait at least 1 week of production use
- Verify all functionality works
- Export old data if needed for records
- Then run: `python manage.py migrate machining zero` (removes all machining tables)

---

## ⏱️ Timeline Summary

| Phase | Duration | Can Fail? |
|-------|----------|-----------|
| Preparation | 10 min | No |
| Run Migrations | 5 min | Yes - rollback if errors |
| Dry Run | 5 min | No (just testing) |
| Execute Migration | 15-30 min | Yes - can resume if fails |
| Validation | 5 min | Detection only |
| Recompute Costs | 10-20 min | Optional |
| Restart App | 5 min | No |
| Verification | 10 min | No |
| **TOTAL** | **65-90 min** | |

---

## 🆘 Emergency Contacts

Before starting, ensure you have:
- [ ] Database backup verified
- [ ] Access to restore backups
- [ ] Contact info for:
  - Database admin
  - Server admin
  - Development team lead

---

## 📞 Support Commands

```bash
# Check migration progress
tail -f migration.log  # if you redirect output

# Stop cost recomputation if needed
touch recompute_part_costs.stop

# Check database sizes
psql -d your_database -c "SELECT pg_size_pretty(pg_database_size('your_database'));"

# Count records in new tables
psql -d your_database -c "SELECT
  (SELECT COUNT(*) FROM tasks_part) as parts,
  (SELECT COUNT(*) FROM tasks_operation) as operations,
  (SELECT COUNT(*) FROM tasks_partcostagg) as costs;"
```

Good luck! 🚀
