# projects/services/selling_price.py
"""
Derived ("representative") selling prices across the job-order tree.

A price is usually recorded at one level only — either on the parent that
carries the sales offer, or on the individual children. The other level then
reads as 0.00 while still accumulating cost, which makes a child look like a
pure loss (e.g. 293-03-11: 22.955 EUR of cost against no revenue, while its
parent 293-03 holds the whole 270.000 EUR offer).

This module fills in the missing side, in both directions:

  * **parent -> children** (``allocated_from_parent``): the priced ancestor's
    amount is split across descendants in proportion to ``total_weight_kg``,
    applied level by level so grandchildren get a share of their parent's share.
  * **children -> parent** (``rolled_up_from_children``): a parent with no price
    of its own shows the sum of the prices its descendants carry.

**The derived value is never written to the authoritative field.** Callers keep
exposing the entered price as ``selling_price``/``selling_price_eur`` and use the
derived value only for display and margin. Anything that SUMs revenue must keep
summing the authoritative field, otherwise a parent and its children would both
contribute and revenue would be counted twice.

Read-only — nothing here writes to the DB.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_Q2 = Decimal("0.01")
_ZERO = Decimal("0")


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_Q2, rounding=ROUND_HALF_UP)


class DerivedSellingPriceResolver:
    """
    Resolves derived prices for a set of job orders.

    Expands each requested job to its whole tree (up to the root, then down
    through every descendant) because both directions need the full picture,
    then computes everything in memory. Build once per request and reuse.
    """

    def __init__(self, job_nos):
        self._derived: dict[str, dict] = {}
        self._own_eur: dict[str, Decimal] = {}
        job_nos = [j for j in set(job_nos or []) if j]
        if not job_nos:
            return
        self._load(job_nos)
        self._compute()

    # ---------- loading ----------

    def _fetch(self, **flt):
        """
        One level of JobOrders. Both select_related/prefetch avoid a query *per
        node* inside `_effective_selling_price`: `offer_phase_shares()` reads
        `offer.items` and `phase_quantity_fraction()` dereferences
        `source_job_order`. Without them a 50-row page issued 270+ extra queries.
        """
        from projects.models import JobOrder
        return list(
            JobOrder.objects.filter(**flt)
            .select_related("source_offer", "source_job_order")
            .prefetch_related("source_offer__items")
        )

    def _absorb(self, objs):
        """Index a batch of JobOrders and compute their own effective prices."""
        from projects.models import JobOrderCostSummary
        from sales.models import SalesOfferPriceRevision
        from projects.services.costing import _effective_selling_price

        objs = [o for o in objs if o.job_no not in self._nodes]
        if not objs:
            return []

        for o in objs:
            self._nodes[o.job_no] = o
            self._weight[o.job_no] = Decimal(str(o.total_weight_kg or 0))
            if o.parent_id:
                self._children.setdefault(o.parent_id, []).append(o.job_no)

        nos = [o.job_no for o in objs]
        summaries = {
            s.job_order_id: s
            for s in JobOrderCostSummary.objects.filter(job_order_id__in=nos)
        }

        offer_ids = {getattr(o, "source_offer_id", None) for o in objs}
        offer_ids.discard(None)
        new_offers = offer_ids - self._priced_offers
        if new_offers:
            self._price_map.update({
                r.offer_id: r
                for r in SalesOfferPriceRevision.objects.filter(
                    offer_id__in=new_offers, is_current=True
                )
            })
            self._priced_offers |= new_offers
        ctx = {"current_price_map": self._price_map}

        # is_phased_master() runs an EXISTS per row unless pre-annotated; derive
        # it from the batch instead.
        phased = {
            src for src, parent in (
                (getattr(o, "source_job_order_id", None), o.parent_id) for o in objs
            )
            if src is not None and src != parent
        }
        for o in objs:
            o._is_phased_master = o.job_no in phased
            eff = _effective_selling_price(o, summaries.get(o.job_no), ctx)
            self._own_eur[o.job_no] = Decimal(str(eff["amount_eur"] or 0))
        return objs

    def _load(self, job_nos):
        from projects.models import JobOrder

        self._nodes: dict[str, object] = {}
        self._children: dict[str, list[str]] = {}
        self._weight: dict[str, Decimal] = {}
        self._price_map: dict = {}
        self._priced_offers: set = set()

        # Pass 1 — just the rows we were asked about. A job that already carries
        # its own price needs nothing further, and most do (601 of 748 in this
        # dataset), so expanding every tree up front would be almost all waste.
        self._absorb(self._fetch(job_no__in=list(job_nos)))

        needy = [
            j for j in job_nos
            if j in self._nodes and self._own_eur.get(j, _ZERO) <= 0
        ]
        if not needy:
            return

        # Pass 2 — only for jobs with no price of their own: walk up to their
        # root (a priced ancestor may be several levels up, and the allocation
        # denominator needs every sibling), then load that root's whole subtree.
        roots: set[str] = set()
        frontier = set(needy)
        seen = set(frontier)
        while frontier:
            rows = dict(
                JobOrder.objects.filter(job_no__in=frontier)
                .values_list("job_no", "parent_id")
            )
            frontier = set()
            for jno, pid in rows.items():
                if pid is None:
                    roots.add(jno)          # itself a root — roll-up candidate
                elif pid not in seen:
                    seen.add(pid)
                    frontier.add(pid)

        objs = self._fetch(job_no__in=list(roots))
        while objs:
            # Descend from everything fetched, not just what _absorb kept —
            # nodes already indexed in pass 1 still have children to visit.
            self._absorb(objs)
            objs = self._fetch(parent_id__in=[o.job_no for o in objs])

    # ---------- computation ----------

    def _subtree_weight(self, jno: str) -> Decimal:
        cached = self._subtree_cache.get(jno)
        if cached is not None:
            return cached
        total = self._weight.get(jno, _ZERO)
        for c in self._children.get(jno, ()):
            total += self._subtree_weight(c)
        self._subtree_cache[jno] = total
        return total

    def _compute(self):
        self._subtree_cache: dict[str, Decimal] = {}

        # --- direction 1: priced ancestor -> unpriced descendants, by weight ---
        for jno in self._nodes:
            if self._own_eur.get(jno, _ZERO) > 0:
                self._allocate(jno, self._own_eur[jno], jno)

        # --- direction 2: unpriced parent -> sum of what its descendants carry ---
        for jno in self._nodes:
            if self._own_eur.get(jno, _ZERO) > 0 or jno in self._derived:
                continue
            total = self._rolled_up(jno)
            if total > 0:
                self._derived[jno] = {
                    "amount_eur": str(_q2(total)),
                    "source": "rolled_up_from_children",
                    "basis": {"from_job_no": None, "note": "alt işlerin toplamı"},
                }

    def _allocate(self, parent_no: str, amount: Decimal, origin_no: str):
        """
        Split ``amount`` across ``parent_no``'s direct children by subtree weight.

        The denominator includes every weighted child, including any that carry
        their own price — so the shares of the rest are never inflated to cover a
        sibling that already has revenue. Children with their own price keep it
        and are not descended into; their own amount is allocated separately when
        the main loop reaches them.
        """
        kids = self._children.get(parent_no, ())
        if not kids:
            return
        weights = {k: self._subtree_weight(k) for k in kids}
        total_w = sum(w for w in weights.values() if w > 0)
        if total_w <= 0:
            return  # no weights recorded — cannot split soundly, leave at 0

        # Quantise every share, then push the rounding remainder onto the largest
        # one so the children add up to the parent amount exactly. Without this a
        # 13-way split drifts a couple of kuruş, which looks like an error when
        # someone expands a parent and adds the column up.
        targets = [
            k for k in kids
            if weights[k] > 0 and self._own_eur.get(k, _ZERO) <= 0
        ]
        if not targets:
            return
        shares = {k: _q2(amount * weights[k] / total_w) for k in targets}
        # Only absorb the remainder when the whole amount was split here; if some
        # of it went to siblings that keep their own price, there is no remainder
        # to reclaim.
        if len(targets) == len([k for k in kids if weights[k] > 0]):
            drift = _q2(amount) - sum(shares.values())
            if drift:
                biggest = max(targets, key=lambda k: shares[k])
                shares[biggest] += drift

        for k in targets:
            share = shares[k]
            self._derived[k] = {
                "amount_eur": str(share),
                "source": "allocated_from_parent",
                "basis": {
                    "from_job_no": origin_no,
                    "from_amount_eur": str(_q2(amount)),
                    "weight_kg": str(weights[k]),
                    "total_weight_kg": str(total_w),
                },
            }
            self._allocate(k, share, origin_no)

    def _rolled_up(self, jno: str) -> Decimal:
        total = _ZERO
        for k in self._children.get(jno, ()):
            own = self._own_eur.get(k, _ZERO)
            total += own if own > 0 else self._rolled_up(k)
        return total

    # ---------- public API ----------

    def get(self, job_no: str):
        """Derived price dict for ``job_no``, or None when it has its own price."""
        return self._derived.get(job_no)

    def own_eur(self, job_no: str) -> Decimal:
        """The job's own effective price in EUR (0 when it carries none)."""
        return self._own_eur.get(job_no, _ZERO)

    def display_for(self, job_no: str) -> dict:
        """``display()`` using the resolver's own computed price — for callers
        that hold the price in a currency other than EUR."""
        return self.display(job_no, self._own_eur.get(job_no, _ZERO))

    def display(self, job_no: str, own_amount_eur) -> dict:
        """
        What to show for this job:
          {'amount_eur': str, 'source': str, 'is_derived': bool, 'basis': dict|None}

        ``source`` is 'own' when the entered price stands, otherwise
        'allocated_from_parent' / 'rolled_up_from_children' / 'none'.
        """
        own = Decimal(str(own_amount_eur or 0))
        if own > 0:
            return {
                "amount_eur": str(_q2(own)),
                "source": "own",
                "is_derived": False,
                "basis": None,
            }
        d = self._derived.get(job_no)
        if d:
            return {
                "amount_eur": d["amount_eur"],
                "source": d["source"],
                "is_derived": True,
                "basis": d.get("basis"),
            }
        return {
            "amount_eur": str(_q2(own)),
            "source": "none",
            "is_derived": False,
            "basis": None,
        }
