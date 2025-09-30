# machining/fx_utils.py
from __future__ import annotations
from bisect import bisect_right
from decimal import Decimal
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from django.utils import timezone
from core.models import CurrencyRateSnapshot  # adjust if the model is elsewhere

IST = ZoneInfo("Europe/Istanbul")

def build_fx_lookup(quote: str = "EUR") -> Callable:
    """
    Returns fx(local_date: date) -> Decimal(TRY->quote) using the last snapshot
    on/before local_date. If no prior snapshot exists, falls back to earliest.
    """
    snaps = list(
        CurrencyRateSnapshot.objects
        .order_by("date")
        .values("date", "rates", "base")
    )
    if not snaps:
        def _no_data(_d): return Decimal("0")
        return _no_data

    dates = [s["date"] for s in snaps]
    values = [Decimal(str((s["rates"] or {}).get(quote, 0))) for s in snaps]

    def fx(local_date) -> Decimal:
        idx = bisect_right(dates, local_date) - 1
        if idx < 0:
            idx = 0  # earliest known (you can choose Decimal("0") to skip costing instead)
        return values[idx]

    return fx
