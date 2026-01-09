"""
Management command to migrate selected_plate data to RemnantPlateUsage.

This command migrates existing selected_plate relationships to the new
RemnantPlateUsage through model. For each CncTask with a selected_plate,
it creates a RemnantPlateUsage record with quantity_used=1.

As per requirements:
- quantity_used is always set to 1
- If the RemnantPlate quantity is more than 1, it will be set to 1

Usage:
    python manage.py migrate_remnant_plates [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.db import connection
from cnc_cutting.models import CncTask, RemnantPlate, RemnantPlateUsage


class Command(BaseCommand):
    help = 'Migrate selected_plate data to RemnantPlateUsage model'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Check if selected_plate field still exists
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name='cnc_cutting_cnctask'
                AND column_name='selected_plate_id'
            """)
            has_selected_plate = cursor.fetchone() is not None

        if not has_selected_plate:
            self.stdout.write(
                self.style.WARNING(
                    'The selected_plate field no longer exists in the database. '
                    'Migration may have already been completed or the field was never created.'
                )
            )

            # Check if there are existing RemnantPlateUsage records
            usage_count = RemnantPlateUsage.objects.count()
            if usage_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Found {usage_count} existing RemnantPlateUsage records. '
                        'Migration appears to have been completed already.'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        'No RemnantPlateUsage records found. If you had tasks with selected plates, '
                        'the data may have been lost during migration.'
                    )
                )
            return

        # Get all tasks with selected plates using raw SQL
        # Note: CncTask uses 'key' as primary key, not 'id'
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT key, selected_plate_id
                FROM cnc_cutting_cnctask
                WHERE selected_plate_id IS NOT NULL
            """)
            tasks_with_plates = cursor.fetchall()

        if not tasks_with_plates:
            self.stdout.write(
                self.style.SUCCESS('No tasks with selected plates found. Nothing to migrate.')
            )
            return

        self.stdout.write(
            self.style.NOTICE(f'Found {len(tasks_with_plates)} tasks with selected plates')
        )

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes will be made\n'))

        migrated_count = 0
        plates_updated = set()

        for task_key, plate_id in tasks_with_plates:
            try:
                task = CncTask.objects.get(key=task_key)
                plate = RemnantPlate.objects.get(id=plate_id)

                self.stdout.write(
                    f'  Task {task_key} -> Plate {plate_id} (quantity: {plate.quantity})'
                )

                if not dry_run:
                    # Create usage record
                    RemnantPlateUsage.objects.create(
                        cnc_task=task,
                        remnant_plate=plate,
                        quantity_used=1
                    )

                    # Update plate quantity to 1 if it's greater
                    if plate.quantity and plate.quantity > 1:
                        plate.quantity = 1
                        plate.save(update_fields=['quantity'])
                        plates_updated.add(plate_id)

                migrated_count += 1

            except CncTask.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'  Task {task_key} not found, skipping')
                )
            except RemnantPlate.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'  Plate with id {plate_id} not found, skipping')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  Error migrating task {task_key}: {str(e)}')
                )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDRY RUN COMPLETE: Would migrate {migrated_count} task-plate relationships'
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Would update {len(plates_updated)} remnant plates to quantity=1'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nSuccessfully migrated {migrated_count} task-plate relationships'
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f'Updated {len(plates_updated)} remnant plates to quantity=1'
                )
            )
            self.stdout.write(
                self.style.NOTICE(
                    '\nYou can now run the migration to remove the selected_plate field: '
                    'python manage.py migrate'
                )
            )
