from django.core.management.base import BaseCommand
from django.conf import settings
import os


class Command(BaseCommand):
    help = 'Signals the recompute_job_costs command to stop gracefully.'

    def handle(self, *args, **options):
        stop_file_path = settings.BASE_DIR / 'recompute_job_costs.stop'

        if os.path.exists(stop_file_path):
            self.stdout.write(self.style.WARNING('Stop signal has already been sent.'))
            return

        # Create the stop file
        with open(stop_file_path, 'w') as f:
            pass  # Just create the file
        self.stdout.write(self.style.SUCCESS('Stop signal sent. The recomputation process will stop after finishing current tasks.'))