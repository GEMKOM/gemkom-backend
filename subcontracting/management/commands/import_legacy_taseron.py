"""
Management command to import legacy subcontracting data from the Taseron Excel sheet.

Usage:
    python manage.py import_legacy_taseron            # Run the import
    python manage.py import_legacy_taseron --dry-run  # Preview without writing

After import, create a statement manually via the UI for "Eski Taşeron (Devir)".
The statement will show 28 line items with full costs (delta=100% for each assignment).
Once approved, last_billed_progress is locked to 100 automatically.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction


LEGACY_NAME = 'Eski Taşeron (Devir)'
LEGACY_SHORT_NAME = 'Eski Taşeron'

# (job_no, total_try, weight_kg)
LEGACY_DATA = [
    ('273-02-01',  Decimal('3629058.99'),   Decimal('206357.00')),
    ('273-02-02',  Decimal('971329.50'),    Decimal('48092.00')),
    ('273-02-03',  Decimal('3841745.13'),   Decimal('241736.50')),
    ('273-02-04',  Decimal('4615995.62'),   Decimal('176371.00')),
    ('273-02-05',  Decimal('1243582.68'),   Decimal('61305.40')),
    ('273-02-06',  Decimal('227297.20'),    Decimal('7331.20')),
    ('273-03',     Decimal('1263198.71'),   Decimal('100531.00')),
    ('273-04',     Decimal('12057.50'),     Decimal('3710.00')),
    ('280-03-02',  Decimal('386657.36'),    Decimal('30345.00')),
    ('280-03-03',  Decimal('665683.52'),    Decimal('50137.00')),
    ('280-03-04',  Decimal('768747.58'),    Decimal('51765.00')),
    ('RM045-12',   Decimal('97344.00'),     Decimal('3042.00')),
    ('RM256-15',   Decimal('110821.90'),    Decimal('8640.00')),
    ('RM262-01-01',Decimal('16565110.89'),  Decimal('692179.25')),
    ('RM262-01-04',Decimal('1014713.53'),   Decimal('17434.50')),
    ('RM262-01-11',Decimal('215677.50'),    Decimal('12270.00')),
    ('RM262-01-12',Decimal('38166.00'),     Decimal('954.00')),
    ('RM262-02-05',Decimal('137931.25'),    Decimal('5740.00')),
    ('RM262-02-08',Decimal('72052.50'),     Decimal('22170.00')),
    ('RM262-02-10',Decimal('69587.50'),     Decimal('5800.00')),
    ('RM262-02-14',Decimal('59910.00'),     Decimal('1997.00')),
    ('RM262-02-15',Decimal('696604.42'),    Decimal('35315.00')),
    ('RM262-03-02',Decimal('6506.50'),      Decimal('2002.00')),
    ('RM262-04-01',Decimal('229068.00'),    Decimal('6363.00')),
    ('RM262-04-02',Decimal('1717744.52'),   Decimal('69792.70')),
    ('RM262-04-03',Decimal('1417763.89'),   Decimal('72993.10')),
    ('RM262-04-04',Decimal('3301422.89'),   Decimal('92768.30')),
    ('RM262-07-02',Decimal('96957.00'),     Decimal('3231.90')),
]


class Command(BaseCommand):
    help = 'Import legacy subcontracting data for "Eski Taşeron (Devir)"'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview actions without writing to the database.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN MODE: no changes will be written ---\n'))

        from projects.models import JobOrder, JobOrderDepartmentTask
        from subcontracting.models import (
            Subcontractor,
            SubcontractingPriceTier,
            SubcontractingAssignment,
        )

        counters = {
            'subcontractor_created': 0,
            'tier_created': 0,
            'tier_skipped': 0,
            'task_created': 0,
            'task_skipped': 0,
            'assignment_created': 0,
            'assignment_skipped': 0,
            'row_error': 0,
        }

        with transaction.atomic():
            # --- Step 1: Get or create the legacy subcontractor ---
            subcontractor = Subcontractor.objects.filter(name=LEGACY_NAME).first()
            if subcontractor:
                self.stdout.write(f'Subcontractor already exists: {LEGACY_NAME} (id={subcontractor.pk})')
            else:
                if not dry_run:
                    subcontractor = Subcontractor.objects.create(
                        name=LEGACY_NAME,
                        short_name=LEGACY_SHORT_NAME,
                        default_currency='TRY',
                        is_active=False,
                    )
                counters['subcontractor_created'] += 1
                self.stdout.write(self.style.SUCCESS(
                    f'{"[DRY RUN] Would create" if dry_run else "Created"} subcontractor: {LEGACY_NAME}'
                ))

            # --- Step 2: Process each row ---
            for job_no, total_try, weight_kg in LEGACY_DATA:
                self.stdout.write(f'\nProcessing {job_no} ...')

                # Look up JobOrder
                try:
                    job_order = JobOrder.objects.get(job_no=job_no)
                except JobOrder.DoesNotExist:
                    self.stderr.write(self.style.ERROR(f'  SKIP: JobOrder not found: {job_no}'))
                    counters['row_error'] += 1
                    continue

                # Find the first welding task
                welding_task = (
                    JobOrderDepartmentTask.objects
                    .filter(job_order=job_order, task_type='welding')
                    .order_by('sequence', 'pk')
                    .first()
                )
                if welding_task is None:
                    self.stderr.write(self.style.ERROR(
                        f'  SKIP: No welding task (task_type=welding) found for {job_no}'
                    ))
                    counters['row_error'] += 1
                    continue

                self.stdout.write(f'  Job: {job_order.title} | Welding task: [{welding_task.pk}] {welding_task.title}')

                # --- Ensure job_order.total_weight_kg can accommodate this tier ---
                # Mirror the serializer validation: sum all non-paint tiers except our own legacy tier
                from django.db.models import Sum as _Sum
                from subcontracting.services.painting import PAINT_TIER_NAME
                existing_tier_weight = (
                    SubcontractingPriceTier.objects
                    .filter(job_order=job_order)
                    .exclude(name=PAINT_TIER_NAME)
                    .exclude(name=LEGACY_NAME)
                    .aggregate(t=_Sum('allocated_weight_kg'))['t'] or Decimal('0')
                )
                required_total = existing_tier_weight + weight_kg
                current_total = job_order.total_weight_kg or Decimal('0')
                if current_total < required_total:
                    self.stdout.write(self.style.WARNING(
                        f'  total_weight_kg ({current_total} kg) is less than required '
                        f'({required_total} kg) — '
                        f'{"would update" if dry_run else "updating"} to {required_total} kg'
                    ))
                    if not dry_run:
                        job_order.total_weight_kg = required_total
                        job_order.save(update_fields=['total_weight_kg'])

                # --- Price tier ---
                tier = SubcontractingPriceTier.objects.filter(
                    job_order=job_order, name=LEGACY_NAME
                ).first()
                if tier:
                    self.stdout.write(f'  Price tier already exists (id={tier.pk}), skipping.')
                    counters['tier_skipped'] += 1
                else:
                    price_per_kg = (total_try / weight_kg).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
                    if not dry_run:
                        tier = SubcontractingPriceTier.objects.create(
                            job_order=job_order,
                            name=LEGACY_NAME,
                            price_per_kg=price_per_kg,
                            currency='TRY',
                            allocated_weight_kg=weight_kg,
                        )
                    counters['tier_created'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  {"[DRY RUN] Would create" if dry_run else "Created"} price tier: '
                        f'{weight_kg} kg @ {price_per_kg} TRY/kg'
                    ))

                # --- Subcontracting subtask ---
                existing_subtask = (
                    JobOrderDepartmentTask.objects
                    .filter(parent=welding_task, task_type='subcontracting', title=LEGACY_NAME)
                    .first()
                )
                if existing_subtask:
                    subtask = existing_subtask
                    self.stdout.write(f'  Subtask already exists (id={subtask.pk}), skipping.')
                    counters['task_skipped'] += 1
                else:
                    from django.db.models import Max
                    max_seq = welding_task.subtasks.aggregate(m=Max('sequence'))['m'] or 0
                    if not dry_run:
                        subtask = JobOrderDepartmentTask.objects.create(
                            job_order=job_order,
                            department=welding_task.department,
                            parent=welding_task,
                            title=LEGACY_NAME,
                            task_type='subcontracting',
                            status='completed',
                            manual_progress=Decimal('100.00'),
                            weight=10,
                            sequence=max_seq + 1,
                        )
                    else:
                        subtask = None
                    counters['task_created'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  {"[DRY RUN] Would create" if dry_run else "Created"} subtask '
                        f'(dept={welding_task.department}, seq={max_seq + 1})'
                    ))

                # --- Assignment ---
                if dry_run:
                    counters['assignment_created'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  [DRY RUN] Would create assignment: {weight_kg} kg, cost={total_try} TRY'
                    ))
                    continue

                # At this point subtask and tier are real objects
                existing_assignment = SubcontractingAssignment.objects.filter(
                    department_task=subtask
                ).first()
                if existing_assignment:
                    self.stdout.write(f'  Assignment already exists (id={existing_assignment.pk}), skipping.')
                    counters['assignment_skipped'] += 1
                else:
                    SubcontractingAssignment.objects.create(
                        department_task=subtask,
                        subcontractor=subcontractor,
                        price_tier=tier,
                        allocated_weight_kg=weight_kg,
                        last_billed_progress=Decimal('0.00'),
                        current_cost=total_try,
                        cost_currency='TRY',
                    )
                    counters['assignment_created'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  Created assignment: {weight_kg} kg, cost={total_try} TRY'
                    ))

            if dry_run:
                transaction.set_rollback(True)

        # --- Summary ---
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS('SUMMARY') if not dry_run else self.style.WARNING('DRY RUN SUMMARY'))
        self.stdout.write(f'  Subcontractors created : {counters["subcontractor_created"]}')
        self.stdout.write(f'  Price tiers created    : {counters["tier_created"]}')
        self.stdout.write(f'  Price tiers skipped    : {counters["tier_skipped"]}')
        self.stdout.write(f'  Subtasks created       : {counters["task_created"]}')
        self.stdout.write(f'  Subtasks skipped       : {counters["task_skipped"]}')
        self.stdout.write(f'  Assignments created    : {counters["assignment_created"]}')
        self.stdout.write(f'  Assignments skipped    : {counters["assignment_skipped"]}')
        self.stdout.write(f'  Rows with errors       : {counters["row_error"]}')
        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                '\nNext step: Create a statement for "Eski Taşeron (Devir)" via the UI. '
                'It will show all 28 assignments at 100% delta. Approve it to lock billing.'
            ))
