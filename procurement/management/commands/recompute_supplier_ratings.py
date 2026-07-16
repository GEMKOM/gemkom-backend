from django.core.management.base import BaseCommand

from procurement.models import Supplier
from procurement.rating_service import recompute_supplier_rating


class Command(BaseCommand):
    help = (
        "Recompute the denormalized rating cache (rating_score, rating_count, "
        "on_time_delivery_pct, last_evaluated_at) for all active suppliers. "
        "Safety net for any missed on_commit trigger; safe to run nightly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--supplier", type=int, default=None,
            help="Recompute only this supplier id.",
        )

    def handle(self, *args, **options):
        supplier_id = options.get("supplier")
        if supplier_id:
            ids = [supplier_id]
        else:
            ids = list(Supplier.objects.values_list("id", flat=True))

        for sid in ids:
            recompute_supplier_rating(sid)

        self.stdout.write(self.style.SUCCESS(f"Recomputed ratings for {len(ids)} supplier(s)."))
