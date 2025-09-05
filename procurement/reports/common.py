from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from django.utils import timezone
from core.models import CurrencyRateSnapshot  # if you keep it here


def bool_param(val: str | None) -> bool | None:
    if val is None:
        return None
    v = val.strip().lower()
    if v in {"1", "true", "yes", "y"}: return True
    if v in {"0", "false", "no", "n"}: return False
    return None

def split_param(val: str | None) -> list[str]:
    if not val: return []
    return [p.strip() for p in val.split(",") if p.strip()]

def q2(x: Decimal | str | float | int) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def extract_rates(snapshot_like: dict | None) -> dict[str, Decimal]:
    """
    Accepts PR.currency_rates_snapshot, {"rates": {...}}, or a flat {CUR: rate} dict.
    Ensures base TRY=1.
    """
    if not isinstance(snapshot_like, dict):
        return {}
    rates = snapshot_like.get("rates") if "rates" in snapshot_like else snapshot_like
    if not isinstance(rates, dict):
        return {}
    out = {}
    for k, v in rates.items():
        if v is not None:
            out[k.upper()] = Decimal(str(v))
    if "TRY" not in out:
        out["TRY"] = Decimal("1")
    return out

def get_fallback_rates() -> dict[str, Decimal]:
    """
    Fallback to today's (or latest) TRY-based snapshot if PR’s snapshot is missing.
    """
    if CurrencyRateSnapshot is None:
        return {}
    today = timezone.now().date()
    snap = (CurrencyRateSnapshot.objects.filter(date=today).first()
            or CurrencyRateSnapshot.objects.order_by("-date").first())
    if snap and getattr(snap, "rates", None):
        return extract_rates({"rates": snap.rates})
    return {}

def to_eur(amount, from_currency: str | None,
           pr_rates: dict[str, Decimal],
           fallback_rates: dict[str, Decimal]) -> Decimal | None:
    """
    Convert amount in from_currency -> EUR.
    Use PR snapshot iff it contains EUR and (TRY or the from_currency);
    otherwise fall back to today's/latest snapshot.
    """

    if amount is None or not from_currency:
        return None

    amt = Decimal(str(amount))
    cur = from_currency.upper()
    if cur in {"TL", "₺"}:
        cur = "TRY"

    # ✅ Early pass-through: no FX needed for EUR
    if cur == "EUR":
        return q2(amt)

    # Decide which rate table to use:
    use_pr = bool(pr_rates) and ("EUR" in pr_rates) and (cur == "TRY" or cur in pr_rates)
    rates = pr_rates if use_pr else fallback_rates

    # If we still don't have usable rates, give up
    if not rates or "EUR" not in rates:
        return None

    if cur == "TRY":
        return q2(amt * rates["EUR"])
    if cur in rates:
        return q2(amt * (rates["EUR"] / rates[cur]))
    return None

