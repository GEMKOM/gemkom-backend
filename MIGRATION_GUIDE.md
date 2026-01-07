# Machining Task → Part/Operation Migration Guide

## Overview
This guide walks you through migrating all machining Tasks to the new Part/Operation system in a single night when there are no active timers.

## Pre-Migration Checklist

### 1. Run Database Migrations
```bash
python manage.py makemigrations tasks
python manage.py migrate
```

This will create:
- `task_key` field on Part model
- PartCostAgg, PartCostAggUser, PartCostRecalcQueue tables

### 2. Verify No Active Timers
```bash
python manage.py check_active_timers
```

Create this command if it doesn't exist, or manually check:
```sql
SELECT COUNT(*) FROM tasks_timer WHERE finish_time IS NULL;
```

Must return 0.

### 3. Backup Database
```bash
pg_dump your_database > backup_before_migration_$(date +%Y%m%d_%H%M%S).sql
```

## Migration Steps (Run at Night)

### Step 1: Create Migration Management Command

Create file: `tasks/management/commands/migrate_tasks_to_parts.py`

```python
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from machining.models import Task as MachiningTask
from tasks.models import Part, Operation, Timer
import time


class Command(BaseCommand):
    help = 'Migrate all machining Tasks to Parts and Operations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making changes'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Get all machining tasks
        tasks = MachiningTask.objects.all().select_related(
            'machine_fk', 'created_by', 'completed_by'
        )

        total = tasks.count()
        self.stdout.write(f"Found {total} tasks to migrate")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        migrated = 0
        failed = 0

        for task in tasks:
            try:
                if not dry_run:
                    self._migrate_task(task)
                migrated += 1

                if migrated % 100 == 0:
                    self.stdout.write(f"Processed {migrated}/{total}...")

            except Exception as e:
                failed += 1
                self.stderr.write(f"Failed to migrate {task.key}: {e}")

        self.stdout.write(self.style.SUCCESS(
            f"\\nMigration complete! Migrated: {migrated}, Failed: {failed}"
        ))

    def _migrate_task(self, task):
        """Migrate a single task to Part + Operation"""
        # Create Part (use PT- prefix to distinguish from old tasks)
        part = Part.objects.create(
            key=f"PT-{task.key}",  # New part key
            task_key=task.key,  # Preserve original task key for drawings
            name=task.name,
            description=task.description,
            job_no=task.job_no,
            image_no=task.image_no,
            position_no=task.position_no,
            quantity=task.quantity,
            material=task.material,
            dimensions=task.dimensions,
            weight_kg=task.weight_kg,
            finish_time=task.finish_time,
            created_by=task.created_by,
            created_at=task.created_at,
            completed_by=task.completed_by,
            completion_date=task.completion_date,
        )

        # Create single Operation for this Part
        operation = Operation.objects.create(
            key=task.key,  # Use original task key for operation
            part=part,
            name=task.name,
            description=task.description,
            order=1,  # First and only operation initially
            interchangeable=False,
            machine_fk=task.machine_fk,
            estimated_hours=task.estimated_hours,
            in_plan=task.in_plan,
            plan_order=task.plan_order,
            planned_start_ms=task.planned_start_ms,
            planned_end_ms=task.planned_end_ms,
            plan_locked=task.plan_locked,
            created_by=task.created_by,
            created_at=task.created_at,
            completed_by=task.completed_by,
            completion_date=task.completion_date,
        )

        # Update all timers to point to the new Operation
        task_ct = ContentType.objects.get_for_model(MachiningTask)
        operation_ct = ContentType.objects.get_for_model(Operation)

        Timer.objects.filter(
            content_type=task_ct,
            object_id=task.key
        ).update(
            content_type=operation_ct,
            object_id=operation.key
        )

        self.stdout.write(f"  Migrated {task.key} → Part {part.key}, Operation {operation.key}")

        return part, operation
```

### Step 2: Migrate Job Cost Data

Create file: `tasks/management/commands/migrate_job_costs.py`

```python
from django.core.management.base import BaseCommand
from django.db import transaction
from machining.models import JobCostAgg, JobCostAggUser
from tasks.models import Part, PartCostAgg, PartCostAggUser


class Command(BaseCommand):
    help = 'Migrate JobCost* tables to PartCost* tables'

    @transaction.atomic
    def handle(self, *args, **options):
        # Migrate JobCostAgg → PartCostAgg
        job_costs = JobCostAgg.objects.all()
        total = job_costs.count()
        self.stdout.write(f"Migrating {total} JobCostAgg records...")

        migrated = 0
        for jc in job_costs:
            try:
                # Find the part by task_key
                part = Part.objects.get(task_key=jc.task_id)

                PartCostAgg.objects.create(
                    part=part,
                    job_no_cached=jc.job_no_cached,
                    currency=jc.currency,
                    hours_ww=jc.hours_ww,
                    hours_ah=jc.hours_ah,
                    hours_su=jc.hours_su,
                    cost_ww=jc.cost_ww,
                    cost_ah=jc.cost_ah,
                    cost_su=jc.cost_su,
                    total_cost=jc.total_cost,
                )
                migrated += 1
            except Part.DoesNotExist:
                self.stderr.write(f"Part not found for task {jc.task_id}")
            except Exception as e:
                self.stderr.write(f"Failed to migrate cost for {jc.task_id}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Migrated {migrated} JobCostAgg records"))

        # Migrate JobCostAggUser → PartCostAggUser
        job_costs_user = JobCostAggUser.objects.all()
        total_user = job_costs_user.count()
        self.stdout.write(f"Migrating {total_user} JobCostAggUser records...")

        migrated_user = 0
        for jcu in job_costs_user:
            try:
                part = Part.objects.get(task_key=jcu.task_id)

                PartCostAggUser.objects.create(
                    part=part,
                    user=jcu.user,
                    job_no_cached=jcu.job_no_cached,
                    currency=jcu.currency,
                    hours_ww=jcu.hours_ww,
                    hours_ah=jcu.hours_ah,
                    hours_su=jcu.hours_su,
                    cost_ww=jcu.cost_ww,
                    cost_ah=jcu.cost_ah,
                    cost_su=jcu.cost_su,
                    total_cost=jcu.total_cost,
                )
                migrated_user += 1
            except Part.DoesNotExist:
                self.stderr.write(f"Part not found for task {jcu.task_id}")
            except Exception as e:
                self.stderr.write(f"Failed to migrate user cost for {jcu.task_id}: {e}")

        self.stdout.write(self.style.SUCCESS(f"Migrated {migrated_user} JobCostAggUser records"))
```

### Step 3: Validation Command

Create file: `tasks/management/commands/validate_migration.py`

```python
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from machining.models import Task as MachiningTask, JobCostAgg
from tasks.models import Part, Operation, Timer, PartCostAgg


class Command(BaseCommand):
    help = 'Validate the migration was successful'

    def handle(self, *args, **options):
        errors = []

        # Check all tasks were migrated
        task_count = MachiningTask.objects.count()
        part_count = Part.objects.filter(task_key__isnull=False).count()

        self.stdout.write(f"Tasks: {task_count}, Parts: {part_count}")
        if task_count != part_count:
            errors.append(f"Task/Part count mismatch: {task_count} tasks but {part_count} parts")

        # Check operations
        operation_count = Operation.objects.count()
        if operation_count != part_count:
            errors.append(f"Operation count mismatch: expected {part_count}, got {operation_count}")

        # Check timers were migrated
        operation_ct = ContentType.objects.get_for_model(Operation)
        timer_count = Timer.objects.filter(content_type=operation_ct).count()
        self.stdout.write(f"Timers pointing to operations: {timer_count}")

        # Check no timers still point to old tasks
        task_ct = ContentType.objects.get_for_model(MachiningTask)
        old_timer_count = Timer.objects.filter(content_type=task_ct).count()
        if old_timer_count > 0:
            errors.append(f"Found {old_timer_count} timers still pointing to old tasks!")

        # Check cost data
        job_cost_count = JobCostAgg.objects.count()
        part_cost_count = PartCostAgg.objects.count()
        self.stdout.write(f"Job costs: {job_cost_count}, Part costs: {part_cost_count}")

        if errors:
            self.stdout.write(self.style.ERROR("\\nValidation FAILED:"))
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  - {error}"))
            return

        self.stdout.write(self.style.SUCCESS("\\nValidation PASSED! Migration successful."))
```

## Execution Order (Night of Migration)

### 1. Stop all services
```bash
# Stop application servers
systemctl stop your-app

# Verify no active timers
python manage.py check_active_timers
```

### 2. Run migrations
```bash
python manage.py makemigrations tasks
python manage.py migrate
```

### 3. Test with dry-run
```bash
python manage.py migrate_tasks_to_parts --dry-run
```

### 4. Execute migration
```bash
python manage.py migrate_tasks_to_parts
```

### 5. Migrate cost data
```bash
python manage.py migrate_job_costs
```

### 6. Validate
```bash
python manage.py validate_migration
```

### 7. Recompute costs (optional, to verify)
```bash
python manage.py recompute_part_costs
```

### 8. Restart services
```bash
systemctl start your-app
```

## Post-Migration Tasks

### Update Frontend
The frontend should continue to work with minimal changes because:
- Operation keys match the old task keys
- All timer endpoints work the same
- Cost calculation happens in background

### Monitor
- Check logs for errors
- Verify timers can be started/stopped
- Verify cost calculations are running
- Check that planning views work

## Rollback Plan

If something goes wrong:

```bash
# Stop services
systemctl stop your-app

# Restore database
psql your_database < backup_before_migration_TIMESTAMP.sql

# Restart services
systemctl start your-app
```

## Notes

- **task_key field**: Preserves the original task key that's written on physical drawings
- **Operation keys**: Keep the same key as the old task for compatibility
- **Part keys**: Use `PT-{task_key}` prefix to distinguish
- **Timers**: Automatically update to point to operations
- **Costs**: Migrated to new tables, calculation logic identical

## Testing Checklist

After migration, test:
- [ ] Can view parts list
- [ ] Can view operations list (with operator and detail views)
- [ ] Can start timer on operation
- [ ] Can stop timer on operation
- [ ] Can view job costs
- [ ] Planning view shows operations correctly
- [ ] Cost calculations run without errors
