# tasks/management/commands/validate_migration.py
from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from machining.models import Task as MachiningTask, JobCostAgg, JobCostAggUser
from tasks.models import Part, Operation, Timer, PartCostAgg, PartCostAggUser


class Command(BaseCommand):
    help = 'Validate the migration was successful'

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*60)
        self.stdout.write("MIGRATION VALIDATION")
        self.stdout.write("="*60 + "\n")

        errors = []
        warnings = []

        # 1. Check all tasks were migrated to parts
        self.stdout.write("1. Checking Tasks → Parts migration...")
        task_count = MachiningTask.objects.count()
        part_count = Part.objects.filter(task_key__isnull=False).count()

        self.stdout.write(f"   Tasks:  {task_count}")
        self.stdout.write(f"   Parts:  {part_count}")

        if task_count != part_count:
            errors.append(f"Task/Part count mismatch: {task_count} tasks but {part_count} parts")
            self.stdout.write(self.style.ERROR(f"   ✗ MISMATCH: Missing {task_count - part_count} parts"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All tasks migrated to parts"))

        # 2. Check operations were created
        self.stdout.write("\n2. Checking Operations creation...")
        operation_count = Operation.objects.count()
        self.stdout.write(f"   Operations: {operation_count}")

        if operation_count != part_count:
            errors.append(f"Operation count mismatch: expected {part_count}, got {operation_count}")
            self.stdout.write(self.style.ERROR(f"   ✗ MISMATCH: Expected {part_count}, got {operation_count}"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All parts have operations"))

        # 3. Check each part has exactly 1 operation
        self.stdout.write("\n3. Checking Part→Operation relationship...")
        parts_with_wrong_op_count = 0
        for part in Part.objects.filter(task_key__isnull=False):
            op_count = part.operations.count()
            if op_count != 1:
                parts_with_wrong_op_count += 1

        if parts_with_wrong_op_count > 0:
            errors.append(f"{parts_with_wrong_op_count} parts don't have exactly 1 operation")
            self.stdout.write(self.style.ERROR(f"   ✗ {parts_with_wrong_op_count} parts have wrong operation count"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All parts have exactly 1 operation"))

        # 4. Check timers were migrated
        self.stdout.write("\n4. Checking Timer migration...")
        operation_ct = ContentType.objects.get_for_model(Operation)
        timer_count = Timer.objects.filter(content_type=operation_ct).count()
        self.stdout.write(f"   Timers on operations: {timer_count}")

        # Check no timers still point to old tasks
        task_ct = ContentType.objects.get_for_model(MachiningTask)
        old_timer_count = Timer.objects.filter(content_type=task_ct).count()

        if old_timer_count > 0:
            errors.append(f"{old_timer_count} timers still point to old machining tasks")
            self.stdout.write(self.style.ERROR(f"   ✗ {old_timer_count} timers still on old tasks!"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ No timers pointing to old tasks"))

        # 5. Check cost data migration
        self.stdout.write("\n5. Checking Cost data migration...")
        job_cost_count = JobCostAgg.objects.count()
        part_cost_count = PartCostAgg.objects.count()

        self.stdout.write(f"   JobCostAgg:  {job_cost_count}")
        self.stdout.write(f"   PartCostAgg: {part_cost_count}")

        if job_cost_count != part_cost_count:
            warnings.append(f"Cost count mismatch: {job_cost_count} job costs but {part_cost_count} part costs")
            self.stdout.write(self.style.WARNING(f"   ⚠ Cost count mismatch (may be expected if some tasks have no costs)"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All costs migrated"))

        # 6. Check per-user costs
        self.stdout.write("\n6. Checking Per-user cost migration...")
        job_cost_user_count = JobCostAggUser.objects.count()
        part_cost_user_count = PartCostAggUser.objects.count()

        self.stdout.write(f"   JobCostAggUser:  {job_cost_user_count}")
        self.stdout.write(f"   PartCostAggUser: {part_cost_user_count}")

        if job_cost_user_count != part_cost_user_count:
            warnings.append(f"User cost count mismatch: {job_cost_user_count} vs {part_cost_user_count}")
            self.stdout.write(self.style.WARNING("   ⚠ User cost count mismatch"))
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All user costs migrated"))

        # 7. Spot check: Verify a few random parts have correct data
        self.stdout.write("\n7. Spot checking data integrity...")
        sample_parts = Part.objects.filter(task_key__isnull=False)[:5]
        spot_check_pass = True

        for part in sample_parts:
            # Check operation exists with same key as task_key
            if not Operation.objects.filter(key=part.task_key).exists():
                errors.append(f"Part {part.key} missing operation with key {part.task_key}")
                spot_check_pass = False

        if spot_check_pass:
            self.stdout.write(self.style.SUCCESS("   ✓ Spot check passed"))
        else:
            self.stdout.write(self.style.ERROR("   ✗ Spot check failed"))

        # Summary
        self.stdout.write("\n" + "="*60)
        if errors:
            self.stdout.write(self.style.ERROR("VALIDATION FAILED"))
            self.stdout.write("\nErrors:")
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  ✗ {error}"))
        else:
            self.stdout.write(self.style.SUCCESS("VALIDATION PASSED"))

        if warnings:
            self.stdout.write("\nWarnings:")
            for warning in warnings:
                self.stdout.write(self.style.WARNING(f"  ⚠ {warning}"))

        self.stdout.write("="*60 + "\n")

        if not errors:
            self.stdout.write(self.style.SUCCESS("Migration successful! ✓"))
            self.stdout.write("\nNext steps:")
            self.stdout.write("1. Test the application thoroughly")
            self.stdout.write("2. Monitor for any errors")
            self.stdout.write("3. If everything works, you can eventually drop old machining tables\n")
