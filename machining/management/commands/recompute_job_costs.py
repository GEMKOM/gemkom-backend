# Non-Django imports are safe at the top level
from django.core.management.base import BaseCommand
from multiprocessing import Pool, cpu_count
import django
import os

def run_recomputation(task_key):
    """
    A top-level helper function that can be pickled for multiprocessing.
    It ensures database connections are handled correctly in each process.
    """
    # Import Django-related modules *inside* the worker function
    from django.conf import settings
    from django.db import close_old_connections

    stop_file_path = settings.BASE_DIR / 'recompute_job_costs.stop'

    try:
        # Check for the stop signal before doing any work
        if os.path.exists(stop_file_path):
            return (task_key, 'CANCELLED', None)

        # ** FIX: Ensure each worker process has the full Django app registry loaded. **
        django.setup()
        # This import must happen *after* django.setup()
        from machining.services.costing import recompute_task_cost_snapshot

        # Close stale database connections from the parent process
        close_old_connections()
        recompute_task_cost_snapshot(task_key)
        # Return a tuple indicating success
        return (task_key, True, None)
    except Exception as e:
        # Return a tuple indicating failure and the error message
        return (task_key, False, str(e))

class Command(BaseCommand):
    help = 'Recomputes job costs for machining tasks'

    def add_arguments(self, parser):
        parser.add_argument(
            '--task_id',
            type=str,
            help='Specific task ID to recompute (optional). If not provided, recomputes all tasks.'
        )
        parser.add_argument(
            '--workers',
            type=int,
            default=cpu_count(),
            help='Number of parallel worker processes to use. Defaults to the number of CPU cores.'
        )

    def handle(self, *args, **options):
        # Import Django models and settings *inside* the handle method
        from machining.models import Task
        from django.conf import settings

        if options['task_id']:
            task_keys = [options['task_id']]
        else:
            # Using iterator() to handle potentially huge querysets without loading all keys into memory at once.
            task_keys = Task.objects.values_list('key', flat=True).iterator()


        stop_file_path = settings.BASE_DIR / 'recompute_job_costs.stop'

        # Ensure no stop file exists from a previous run
        if os.path.exists(stop_file_path):
            os.remove(stop_file_path)

        try:
            num_workers = options['workers']
            self.stdout.write(f"Starting job cost recomputation with {num_workers} worker(s)...")
            self.stdout.write(self.style.NOTICE('To stop, run: python manage.py stop_recompute_job_costs'))

            with Pool(processes=num_workers) as pool:
                results = pool.imap_unordered(run_recomputation, task_keys)

                for task_key, status, message in results:
                    if status is True:
                        self.stdout.write(self.style.SUCCESS(f'Successfully recomputed job cost for task {task_key}'))
                    elif status == 'CANCELLED':
                        self.stdout.write(self.style.WARNING(f'Processing cancelled. Task not started: {task_key}'))
                        # Terminate the pool to stop all other workers immediately
                        pool.terminate() # Prevent the pool from accepting new tasks
                        pool.join()   # Wait for all workers to finish their current tasks
                        break
                    else: # status is False
                        self.stdout.write(self.style.ERROR(f'Error recomputing job cost for task {task_key}: {message}'))
        finally:
            # Clean up the stop file if it exists
            if os.path.exists(stop_file_path):
                os.remove(stop_file_path)
            self.stdout.write(self.style.SUCCESS('Recomputation process finished.'))
