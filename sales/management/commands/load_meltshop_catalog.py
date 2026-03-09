import os
import openpyxl
from django.core.management.base import BaseCommand
from sales.models import OfferTemplate, OfferTemplateNode


AREA_DESCRIPTIONS = {
    'AE': 'Auxiliary Equipment',
    'CCM': 'Continuous Casting Machine',
    'CCS': 'Converter Cooling System',
    'EAF': 'Electric Arc Furnace',
    'EPC': 'Engineering, Procurement and Construction',
    'FESCON': 'Feeding Conveyor System',
    'FTP': 'Fume Treatment Plant',
    'LF': 'Ladle Furnace',
    'MHS': 'Material Handling System',
    'OTHER': 'Other / Uncategorized',
    'VD': 'Vacuum Degassing System',
    'WTP': 'Water Treatment Plant',
}


class Command(BaseCommand):
    help = 'Load Meltshop OfferTemplate and its nodes from output2.xlsx'

    def add_arguments(self, parser):
        parser.add_argument(
            '--xlsx',
            default='output2.xlsx',
            help='Path to the Excel file (default: output2.xlsx in project root)',
        )

    def handle(self, *args, **options):
        xlsx_path = options['xlsx']
        if not os.path.isabs(xlsx_path):
            xlsx_path = os.path.join(os.getcwd(), xlsx_path)

        if not os.path.exists(xlsx_path):
            self.stderr.write(self.style.ERROR(f'File not found: {xlsx_path}'))
            return

        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))[1:]  # skip header row

        # Create or get the Meltshop template
        template, created = OfferTemplate.objects.get_or_create(
            name='Meltshop',
            defaults={'description': 'Meltshop equipment catalog', 'is_active': True},
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Created OfferTemplate: Meltshop'))
        else:
            self.stdout.write('OfferTemplate already exists: Meltshop')

        # Collect unique areas in order of first appearance
        seen_areas = []
        for code, area, name in rows:
            if area and area not in seen_areas:
                seen_areas.append(area)

        # Create area nodes (top-level)
        area_nodes = {}
        for seq, area_code in enumerate(seen_areas, start=1):
            description = AREA_DESCRIPTIONS.get(area_code, '')
            node, created = OfferTemplateNode.objects.get_or_create(
                template=template,
                parent=None,
                title=area_code,
                defaults={
                    'description': description,
                    'sequence': seq,
                    'is_active': True,
                },
            )
            if not created:
                # Update sequence/description in case re-running
                node.sequence = seq
                node.description = description
                node.save(update_fields=['sequence', 'description'])
            area_nodes[area_code] = node
            status = 'Created' if created else 'Exists'
            self.stdout.write(f'  [{status}] Area node: {area_code} — {description}')

        # Create equipment nodes under each area
        equipment_seq = {}  # track sequence per area
        created_count = 0
        skipped_count = 0

        for code, area, name in rows:
            if not area or not name:
                continue
            parent_node = area_nodes.get(area)
            if parent_node is None:
                self.stdout.write(self.style.WARNING(f'  Skipping unknown area: {area}'))
                continue

            seq = equipment_seq.get(area, 0) + 1
            equipment_seq[area] = seq

            node, created = OfferTemplateNode.objects.get_or_create(
                template=template,
                parent=parent_node,
                title=name,
                defaults={
                    'code': code,
                    'sequence': seq,
                    'is_active': True,
                },
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDone. Equipment nodes created: {created_count}, already existed: {skipped_count}'
            )
        )
