# tasks/management/commands/migrate_job_costs.py
from django.core.management.base import BaseCommand
from django.db import transaction
from machining.models import JobCostAgg, JobCostAggUser
from tasks.models import Part, PartCostAgg, PartCostAggUser


class Command(BaseCommand):
    help = 'Migrate JobCost* tables to PartCost* tables'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without making changes (preview only)'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE - No changes will be made ===\n"))

        # Migrate JobCostAgg → PartCostAgg
        self.stdout.write("Migrating JobCostAgg → PartCostAgg...")
        job_costs = JobCostAgg.objects.all()
        total = job_costs.count()
        self.stdout.write(f"Found {total} JobCostAgg records\n")

        migrated = 0
        skipped = 0
        failed = 0

        for jc in job_costs:
            try:
                # Find the part by task_key
                try:
                    part = Part.objects.get(task_key=jc.task_id)
                except Part.DoesNotExist:
                    self.stderr.write(f"  ✗ Part not found for task {jc.task_id}")
                    failed += 1
                    continue

                # Check if already migrated
                if PartCostAgg.objects.filter(part=part).exists():
                    skipped += 1
                    continue

                if not dry_run:
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
                    self.stdout.write(f"  ✓ Migrated cost for {jc.task_id} → {part.key}")
                else:
                    self.stdout.write(f"  [DRY RUN] Would migrate cost for {jc.task_id} → {part.key}")

                migrated += 1

            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f"  ✗ Failed to migrate cost for {jc.task_id}: {e}"))

        self.stdout.write(f"\nJobCostAgg: Migrated {migrated}, Skipped {skipped}, Failed {failed}\n")

        # Migrate JobCostAggUser → PartCostAggUser
        self.stdout.write("Migrating JobCostAggUser → PartCostAggUser...")
        job_costs_user = JobCostAggUser.objects.all()
        total_user = job_costs_user.count()
        self.stdout.write(f"Found {total_user} JobCostAggUser records\n")

        migrated_user = 0
        skipped_user = 0
        failed_user = 0

        for jcu in job_costs_user:
            try:
                try:
                    part = Part.objects.get(task_key=jcu.task_id)
                except Part.DoesNotExist:
                    failed_user += 1
                    continue

                # Check if already migrated
                if PartCostAggUser.objects.filter(part=part, user=jcu.user).exists():
                    skipped_user += 1
                    continue

                if not dry_run:
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

                if migrated_user % 100 == 0:
                    self.stdout.write(f"  Progress: {migrated_user}/{total_user}...")

            except Exception as e:
                failed_user += 1
                self.stderr.write(f"  ✗ Failed user cost for {jcu.task_id}/{jcu.user_id}: {e}")

        self.stdout.write(f"\nJobCostAggUser: Migrated {migrated_user}, Skipped {skipped_user}, Failed {failed_user}\n")

        # Summary
        self.stdout.write("\n" + "="*60)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN COMPLETE (no changes made)"))
        else:
            self.stdout.write(self.style.SUCCESS("COST MIGRATION COMPLETE"))

        self.stdout.write(f"\nJobCostAgg:     {migrated} migrated, {failed} failed")
        self.stdout.write(f"JobCostAggUser: {migrated_user} migrated, {failed_user} failed")
        self.stdout.write("="*60 + "\n")
