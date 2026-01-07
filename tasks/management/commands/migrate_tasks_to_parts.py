# tasks/management/commands/migrate_tasks_to_parts.py
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from machining.models import Task as MachiningTask
from tasks.models import Part, Operation, Timer, TaskKeyCounter
import time


class Command(BaseCommand):
    help = 'Migrate all machining Tasks to Parts and Operations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making changes (preview only)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of tasks to migrate (for testing)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        limit = options.get('limit')

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE - No changes will be made ===\n"))

        # Get all machining tasks
        tasks = MachiningTask.objects.all().select_related(
            'machine_fk', 'created_by', 'completed_by'
        ).order_by('key')

        if limit:
            tasks = tasks[:limit]

        total = tasks.count()
        self.stdout.write(f"Found {total} tasks to migrate\n")

        migrated = 0
        failed = 0
        skipped = 0

        for task in tasks:
            try:
                # Check if already migrated
                if Part.objects.filter(task_key=task.key).exists():
                    skipped += 1
                    if skipped % 100 == 0:
                        self.stdout.write(f"  Skipped {skipped} already migrated tasks...")
                    continue

                if not dry_run:
                    with transaction.atomic():
                        part, operation = self._migrate_task(task)
                        self.stdout.write(
                            f"  ✓ Migrated {task.key} → Part: {part.key}, Operation: {operation.key}"
                        )
                else:
                    self.stdout.write(
                        f"  [DRY RUN] Would migrate {task.key} → Part: PT-{task.key}, Operation: {task.key}"
                    )

                migrated += 1

                if migrated % 100 == 0:
                    self.stdout.write(f"\nProgress: {migrated}/{total} migrated, {skipped} skipped...")

            except Exception as e:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(f"  ✗ Failed to migrate {task.key}: {e}")
                )

        # Summary
        self.stdout.write("\n" + "="*60)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN COMPLETE (no changes made)"))
        else:
            self.stdout.write(self.style.SUCCESS("MIGRATION COMPLETE"))

        self.stdout.write(f"\nTotal tasks: {total}")
        self.stdout.write(f"Migrated:    {migrated}")
        self.stdout.write(f"Skipped:     {skipped}")
        self.stdout.write(f"Failed:      {failed}")
        self.stdout.write("="*60 + "\n")

        if not dry_run and migrated > 0:
            self.stdout.write(
                self.style.SUCCESS("\nNext steps:")
            )
            self.stdout.write("1. Run: python manage.py migrate_job_costs")
            self.stdout.write("2. Run: python manage.py validate_migration")
            self.stdout.write("3. Run: python manage.py recompute_part_costs\n")

    def _migrate_task(self, task):
        """Migrate a single task to Part + Operation"""
        # Generate part key using TaskKeyCounter (same as API)
        counter, created = TaskKeyCounter.objects.select_for_update().get_or_create(
            prefix='PT', defaults={'current': 0}
        )
        counter.current += 1
        counter.save()
        part_key = f"PT-{counter.current:03d}"

        # Create Part
        part = Part.objects.create(
            key=part_key,  # Generated key: PT-001, PT-002, etc.
            task_key=task.key,  # Preserve original task key for drawings
            name=task.name,
            description=task.description or '',
            job_no=getattr(task, 'job_no', None),
            image_no=getattr(task, 'image_no', None),
            position_no=getattr(task, 'position_no', None),
            quantity=task.quantity,
            material=getattr(task, 'material', None),
            dimensions=getattr(task, 'dimensions', None),
            weight_kg=getattr(task, 'weight_kg', None),
            finish_time=task.finish_time,
            created_by=task.created_by,
            created_at=task.created_at,
            completed_by=task.completed_by,
            completion_date=task.completion_date,
        )

        # Create single Operation for this Part
        # Key will be auto-generated as {part.key}-OP-{order} in save()
        operation = Operation.objects.create(
            part=part,
            name=task.name,
            description=task.description or '',
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

        updated_timers = Timer.objects.filter(
            content_type=task_ct,
            object_id=task.key
        ).update(
            content_type=operation_ct,
            object_id=operation.key  # Update to new operation key
        )

        if updated_timers > 0:
            self.stdout.write(f"    → Updated {updated_timers} timers to {operation.key}")

        return part, operation
