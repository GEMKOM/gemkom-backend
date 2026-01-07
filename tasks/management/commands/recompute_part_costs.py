# tasks/management/commands/recompute_part_costs.py
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from multiprocessing import Pool, cpu_count
import django
import os


def run_recomputation(part_key):
    """
    Worker function for multiprocessing.
    Must be at top level to be picklable.
    """
    from django.conf import settings

    stop_file_path = settings.BASE_DIR / 'recompute_part_costs.stop'

    try:
        # Check for stop signal
        if os.path.exists(stop_file_path):
            return (part_key, 'CANCELLED', None)

        # Ensure Django is set up in this worker process
        django.setup()

        from tasks.services.costing import recompute_part_cost_snapshot

        # Close stale connections from parent process
        close_old_connections()

        recompute_part_cost_snapshot(part_key)
        return (part_key, True, None)

    except Exception as e:
        return (part_key, False, str(e))


class Command(BaseCommand):
    help = 'Recomputes costs for all parts (or a specific part)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--part-key',
            type=str,
            help='Specific part key to recompute (optional)'
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=cpu_count(),
            help=f'Number of parallel workers (default: {cpu_count()})'
        )

    def handle(self, *args, **options):
        from tasks.models import Part
        from django.conf import settings

        part_key = options.get('part_key')

        # Single part mode
        if part_key:
            self.stdout.write(f"Recomputing costs for part: {part_key}")
            try:
                from tasks.services.costing import recompute_part_cost_snapshot
                recompute_part_cost_snapshot(part_key)
                self.stdout.write(self.style.SUCCESS(f"✓ Successfully recomputed costs for {part_key}"))
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"✗ Failed to recompute {part_key}: {e}"))
            return

        # Bulk mode - all parts
        part_keys = Part.objects.values_list('key', flat=True).iterator()

        stop_file_path = settings.BASE_DIR / 'recompute_part_costs.stop'

        # Remove any existing stop file
        if os.path.exists(stop_file_path):
            os.remove(stop_file_path)

        try:
            num_workers = options['workers']
            self.stdout.write(f"Starting cost recomputation with {num_workers} worker(s)...")
            self.stdout.write(self.style.NOTICE('To stop, run: touch recompute_part_costs.stop'))

            success_count = 0
            fail_count = 0
            cancelled = False

            with Pool(processes=num_workers) as pool:
                results = pool.imap_unordered(run_recomputation, part_keys)

                for part_key, status, message in results:
                    if status is True:
                        success_count += 1
                        if success_count % 50 == 0:
                            self.stdout.write(f"Progress: {success_count} parts processed...")
                    elif status == 'CANCELLED':
                        self.stdout.write(self.style.WARNING(f'✗ Cancelled at: {part_key}'))
                        pool.terminate()
                        pool.join()
                        cancelled = True
                        break
                    else:  # status is False
                        fail_count += 1
                        self.stderr.write(self.style.ERROR(f'✗ Failed {part_key}: {message}'))

            # Summary
            self.stdout.write("\n" + "="*60)
            if cancelled:
                self.stdout.write(self.style.WARNING("RECOMPUTATION CANCELLED"))
            else:
                self.stdout.write(self.style.SUCCESS("RECOMPUTATION COMPLETE"))

            self.stdout.write(f"\nSuccessful: {success_count}")
            self.stdout.write(f"Failed:     {fail_count}")
            self.stdout.write("="*60 + "\n")

        finally:
            # Clean up stop file
            if os.path.exists(stop_file_path):
                os.remove(stop_file_path)
