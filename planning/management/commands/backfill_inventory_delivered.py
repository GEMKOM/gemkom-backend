from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from planning.models import PlanningRequestItem


class Command(BaseCommand):
    help = (
        "Backfill is_delivered on PlanningRequestItems that are fully covered by "
        "inventory (quantity_from_inventory >= quantity) but not yet marked delivered."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without making changes.",
        )

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]

        # Items fully covered by inventory but not yet marked delivered
        qs = PlanningRequestItem.objects.filter(
            quantity_from_inventory__gte=F("quantity"),
            is_delivered=False,
        )

        count = qs.count()

        if count == 0:
            self.stdout.write("No records to update.")
            return

        self.stdout.write(f"Found {count} item(s) to mark as delivered.")

        if dry_run:
            for item in qs.select_related("item"):
                self.stdout.write(
                    f"  [dry-run] PlanningRequestItem #{item.pk} "
                    f"({item.item.code} / job {item.job_no}) "
                    f"qty={item.quantity} from_inv={item.quantity_from_inventory}"
                )
            self.stdout.write(self.style.WARNING("Dry run — no changes made."))
            return

        updated = 0
        with transaction.atomic():
            for item in qs.prefetch_related("inventory_allocations"):
                # Use the most recent allocation for delivered_at / delivered_by
                latest_allocation = item.inventory_allocations.order_by("-allocated_at").first()

                item.is_delivered = True
                item.delivered_at = latest_allocation.allocated_at if latest_allocation else None
                item.delivered_by = latest_allocation.allocated_by if latest_allocation else None
                item.save(update_fields=["is_delivered", "delivered_at", "delivered_by"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Marked {updated} item(s) as delivered."))
