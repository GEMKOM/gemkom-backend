"""
Linear Cutting Optimizer — 1D Bin Packing (First Fit Decreasing)

Given a list of parts (each with a nominal length, quantity, and optional
miter angles) and a stock bar length, this module computes the minimum number
of bars needed and produces a layout (offset positions) for every cut.

Angle offset formula
--------------------
A miter cut on a profile of height H at angle α (degrees) consumes an
additional H × |tan(α)| mm compared to a square cut.  We add this offset
for both ends of the part so that the "effective" length accounts for the
extra bar material consumed by the angled faces.

Kerf
----
Every saw cut removes `kerf_mm` of material.  Between consecutive cuts on the
same bar there is one kerf.  The first cut (at the bar end / entry) is free
because we assume the bar has already been squared off.  So for N parts placed
on a bar there are (N-1) kerfs between them, plus one final trim-cut kerf at
the tail end is NOT counted (it only affects waste, not required capacity).

Actually, industry convention counts one kerf per cut — including the separating
cut after the last piece.  We include a kerf after each placed piece to be
conservative (slightly over-estimates kerf consumption, safer).
"""

import math
from dataclasses import dataclass, field
from typing import List


@dataclass
class PartInstance:
    """A single piece to be cut."""
    label: str
    nominal_mm: int          # requested length
    effective_mm: float      # nominal + angle offsets
    job_no: str = ''
    part_id: int = 0         # LinearCuttingPart.pk
    angle_left_deg: float = 0.0
    angle_right_deg: float = 0.0
    profile_height_mm: int = 0
    image_no: str = ''


@dataclass
class PlacedCut:
    """One part placed on a bar at a given offset."""
    label: str
    nominal_mm: int
    effective_mm: float
    offset_mm: float         # distance from bar start to cut start
    job_no: str = ''
    part_id: int = 0
    angle_left_deg: float = 0.0
    angle_right_deg: float = 0.0
    profile_height_mm: int = 0
    image_no: str = ''
    # Nesting fields — populated only when two complementary-angled parts share one cut
    is_nest_pair: bool = False
    nest_role: str = ''                  # 'A' (left part) | 'B' (right part) | '' for standalone
    nested_with_index: int = None        # index within bar.cuts of the pair partner
    shared_angle_offset_mm: float = 0.0 # the triangle offset that was cancelled


@dataclass
class NestPair:
    """
    Two PartInstances whose shared diagonal cut collapses one angle offset pair.

    The right angle of part_a and the left angle of part_b are equal in magnitude
    and can be produced with a single saw pass.  The pair occupies:
        nominal_A + left_offset_A + nominal_B + right_offset_B  (+1 kerf)
    instead of two separate placements each carrying their own angle offset.
    """
    part_a: PartInstance       # left part on bar; its right angle is absorbed
    part_b: PartInstance       # right part on bar; its left angle is absorbed
    effective_mm: float        # nominal_A + left_offset_A + nominal_B + right_offset_B
    shared_offset_mm: float    # the cancelled offset (right_offset_A == left_offset_B)


@dataclass
class Bar:
    """One stock bar with its placed cuts."""
    bar_index: int
    stock_length_mm: int
    cuts: List[PlacedCut] = field(default_factory=list)
    is_remnant: bool = False
    stock_bar_id: int = 0
    _used_mm: float = field(default=0.0, init=False)

    def remaining(self, kerf_mm: float) -> float:
        """Remaining usable length on this bar (already accounts for kerf after each cut)."""
        return self.stock_length_mm - self._used_mm

    def can_fit(self, effective_mm: float, kerf_mm: float) -> bool:
        used_after = self._used_mm + effective_mm + kerf_mm
        return used_after <= self.stock_length_mm

    def place(self, part: PartInstance, kerf_mm: float) -> PlacedCut:
        offset = self._used_mm
        cut = PlacedCut(
            label=part.label,
            nominal_mm=part.nominal_mm,
            effective_mm=part.effective_mm,
            offset_mm=round(offset, 2),
            job_no=part.job_no,
            part_id=part.part_id,
            angle_left_deg=part.angle_left_deg,
            angle_right_deg=part.angle_right_deg,
            profile_height_mm=part.profile_height_mm,
            image_no=part.image_no,
        )
        self._used_mm += part.effective_mm + kerf_mm
        self.cuts.append(cut)
        return cut

    def can_fit_pair(self, pair, kerf_mm: float) -> bool:
        return self._used_mm + pair.effective_mm + kerf_mm <= self.stock_length_mm

    def place_pair(self, pair, kerf_mm: float):
        """
        Place a NestPair onto this bar as two consecutive PlacedCut entries.

        A's right angle offset and B's left angle offset are absorbed into the
        shared diagonal cut — neither is charged separately.  Only one kerf is
        charged for the whole pair (the separating cut after B).
        """
        left_offset_a = _angle_offset(pair.part_a.angle_left_deg, pair.part_a.profile_height_mm)
        a_span = pair.part_a.nominal_mm + left_offset_a   # A's bar footprint (right offset absorbed)

        right_offset_b = _angle_offset(pair.part_b.angle_right_deg, pair.part_b.profile_height_mm)
        b_span = pair.part_b.nominal_mm + right_offset_b  # B's bar footprint (left offset absorbed)

        offset_a = self._used_mm
        offset_b = offset_a + a_span  # B starts immediately after A — no kerf gap between them

        cut_a = PlacedCut(
            label=pair.part_a.label,
            nominal_mm=pair.part_a.nominal_mm,
            effective_mm=round(a_span, 2),
            offset_mm=round(offset_a, 2),
            job_no=pair.part_a.job_no,
            part_id=pair.part_a.part_id,
            angle_left_deg=pair.part_a.angle_left_deg,
            angle_right_deg=pair.part_a.angle_right_deg,
            profile_height_mm=pair.part_a.profile_height_mm,
            image_no=pair.part_a.image_no,
            is_nest_pair=True,
            nest_role='A',
            shared_angle_offset_mm=round(pair.shared_offset_mm, 2),
        )
        cut_b = PlacedCut(
            label=pair.part_b.label,
            nominal_mm=pair.part_b.nominal_mm,
            effective_mm=round(b_span, 2),
            offset_mm=round(offset_b, 2),
            job_no=pair.part_b.job_no,
            part_id=pair.part_b.part_id,
            angle_left_deg=pair.part_b.angle_left_deg,
            angle_right_deg=pair.part_b.angle_right_deg,
            profile_height_mm=pair.part_b.profile_height_mm,
            image_no=pair.part_b.image_no,
            is_nest_pair=True,
            nest_role='B',
            shared_angle_offset_mm=round(pair.shared_offset_mm, 2),
        )

        self._used_mm += pair.effective_mm + kerf_mm
        self.cuts.append(cut_a)
        self.cuts.append(cut_b)

        # Back-fill cross-references now that both cuts have stable indices
        idx_a = len(self.cuts) - 2
        idx_b = len(self.cuts) - 1
        self.cuts[idx_a].nested_with_index = idx_b
        self.cuts[idx_b].nested_with_index = idx_a

    @property
    def waste_mm(self) -> int:
        return max(0, int(self.stock_length_mm - self._used_mm))


# ─────────────────────────────────────────────────────────────────────────────

def _angle_offset(angle_deg: float, profile_height_mm: int) -> float:
    """Extra mm consumed at one end due to a miter cut."""
    if angle_deg == 0 or profile_height_mm == 0:
        return 0.0
    return profile_height_mm * abs(math.tan(math.radians(angle_deg)))


def _build_instances(parts_data: list) -> List[PartInstance]:
    """
    Expand each part definition into individual PartInstance objects.

    parts_data items must have:
        label, nominal_length_mm, quantity,
        angle_left_deg, angle_right_deg, profile_height_mm,
        job_no (optional), id (optional)
    """
    instances: List[PartInstance] = []
    for p in parts_data:
        left_offset = _angle_offset(float(p.get('angle_left_deg', 0)), int(p.get('profile_height_mm', 0)))
        right_offset = _angle_offset(float(p.get('angle_right_deg', 0)), int(p.get('profile_height_mm', 0)))
        effective = p['nominal_length_mm'] + left_offset + right_offset
        angle_left = float(p.get('angle_left_deg', 0))
        angle_right = float(p.get('angle_right_deg', 0))
        profile_h = int(p.get('profile_height_mm', 0))
        for _ in range(int(p['quantity'])):
            instances.append(PartInstance(
                label=p.get('label', ''),
                nominal_mm=p['nominal_length_mm'],
                effective_mm=effective,
                job_no=p.get('job_no', ''),
                part_id=p.get('id', 0),
                angle_left_deg=angle_left,
                angle_right_deg=angle_right,
                profile_height_mm=profile_h,
                image_no=p.get('image_no', ''),
            ))
    return instances


def _find_pairs(instances: List[PartInstance], kerf_mm: float):
    """
    Greedy opportunistic pairing pass.

    For each unpaired instance A whose right end is angled, find the first
    subsequent unpaired instance B whose left end has an equal-magnitude angle
    and the same profile height.  The pair shares one diagonal cut instead of
    two, saving right_offset_A + left_offset_B mm of bar stock and one saw pass.

    Returns a list of PartInstance | NestPair objects sorted by effective_mm
    descending (FFD order maintained).
    """
    paired: set = set()
    result = []

    for i, a in enumerate(instances):
        if id(a) in paired:
            continue
        # A must have a non-zero right angle on a profiled section to be nestable
        if a.angle_right_deg == 0 or a.profile_height_mm == 0:
            result.append(a)
            continue

        right_offset_a = _angle_offset(a.angle_right_deg, a.profile_height_mm)
        matched = False
        for j in range(i + 1, len(instances)):
            b = instances[j]
            if id(b) in paired:
                continue
            if b.profile_height_mm != a.profile_height_mm:
                continue
            if b.angle_left_deg == 0:
                continue
            if abs(a.angle_right_deg) != abs(b.angle_left_deg):
                continue

            left_offset_a = _angle_offset(a.angle_left_deg, a.profile_height_mm)
            right_offset_b = _angle_offset(b.angle_right_deg, b.profile_height_mm)
            pair_eff = a.nominal_mm + left_offset_a + b.nominal_mm + right_offset_b

            paired.add(id(a))
            paired.add(id(b))
            result.append(NestPair(
                part_a=a,
                part_b=b,
                effective_mm=pair_eff,
                shared_offset_mm=right_offset_a,
            ))
            matched = True
            break

        if not matched and id(a) not in paired:
            result.append(a)

    # Any instances skipped entirely (were paired as B) are now absent — that's correct.
    # Re-sort by effective_mm descending to restore FFD order across pairs and singles.
    result.sort(key=lambda x: x.effective_mm, reverse=True)
    return result


def optimize(
    parts_data: list,
    stock_length_mm: int,
    kerf_mm: float = 3.0,
    stock_pieces: list = None,
) -> dict:
    """
    Run First Fit Decreasing (FFD) bin-packing on the given parts.

    Parameters
    ----------
    parts_data : list of dicts
        Each dict: {label, nominal_length_mm, quantity, angle_left_deg,
                    angle_right_deg, profile_height_mm, job_no?, id?}
    stock_length_mm : int
        Length of a single full stock bar in mm.
    kerf_mm : float
        Blade kerf in mm (material removed per cut).
    stock_pieces : list of dicts, optional
        Pre-existing remnant pieces to use before opening new full bars.
        Each dict: {length_mm: int, quantity: int}
        Pieces that receive no cuts are dropped from the result.

    Returns
    -------
    dict with keys:
        bars_needed (new full bars only), remnant_bars_used,
        total_waste_mm, efficiency_pct, bars (list).
        Each bar has is_remnant: bool.

    Raises
    ------
    ValueError
        If any single part's effective length exceeds the stock bar length.
    """
    instances = _build_instances(parts_data)

    # Validate: no part can exceed the full bar
    for inst in instances:
        if inst.effective_mm > stock_length_mm:
            raise ValueError(
                f"Part '{inst.label}' has effective length {inst.effective_mm:.1f} mm "
                f"which exceeds the stock bar length of {stock_length_mm} mm."
            )

    if not instances:
        return {
            'bars_needed': 0,
            'remnant_bars_used': 0,
            'total_waste_mm': 0,
            'efficiency_pct': 100.0,
            'nest_pairs_formed': 0,
            'material_saved_by_nesting_mm': 0.0,
            'bars': [],
        }

    # Sort descending by effective length (FFD heuristic)
    instances.sort(key=lambda p: p.effective_mm, reverse=True)

    # Opportunistic pairing: form NestPairs where complementary angles allow a shared cut
    packing_items = _find_pairs(instances, kerf_mm)

    # Validate pairs too (a pair's effective_mm is always ≤ sum of its two parts,
    # but could still exceed stock length if both parts are very long)
    for item in packing_items:
        if isinstance(item, NestPair) and item.effective_mm > stock_length_mm:
            raise ValueError(
                f"NestPair ({item.part_a.label} + {item.part_b.label}) has effective "
                f"length {item.effective_mm:.1f} mm exceeding stock bar {stock_length_mm} mm."
            )

    # Pre-seed bars from stock pieces (longest first)
    # Each piece is expanded into `quantity` individual Bar instances,
    # all sharing the same stock_bar_id so confirm can tally usage per ID.
    bars: List[Bar] = []
    if stock_pieces:
        for piece in sorted(stock_pieces, key=lambda p: p['length_mm'], reverse=True):
            for _ in range(int(piece['quantity'])):
                bars.append(Bar(
                    bar_index=len(bars) + 1,
                    stock_length_mm=int(piece['length_mm']),
                    is_remnant=True,
                    stock_bar_id=int(piece.get('id', 0)),
                ))

    for item in packing_items:
        placed = False
        if isinstance(item, NestPair):
            for bar in bars:
                if bar.can_fit_pair(item, kerf_mm):
                    bar.place_pair(item, kerf_mm)
                    placed = True
                    break
            if not placed:
                new_bar = Bar(bar_index=len(bars) + 1, stock_length_mm=stock_length_mm, is_remnant=False)
                new_bar.place_pair(item, kerf_mm)
                bars.append(new_bar)
        else:
            for bar in bars:
                if bar.can_fit(item.effective_mm, kerf_mm):
                    bar.place(item, kerf_mm)
                    placed = True
                    break
            if not placed:
                new_bar = Bar(bar_index=len(bars) + 1, stock_length_mm=stock_length_mm, is_remnant=False)
                new_bar.place(item, kerf_mm)
                bars.append(new_bar)

    # Drop remnant bars that received no cuts (too short for any part)
    bars = [b for b in bars if b.cuts or not b.is_remnant]

    # Re-index after possible drops
    for i, b in enumerate(bars):
        b.bar_index = i + 1

    total_waste = sum(b.waste_mm for b in bars)
    total_stock_mm = sum(b.stock_length_mm for b in bars)
    efficiency = round((1 - total_waste / total_stock_mm) * 100, 2) if total_stock_mm else 0.0

    new_bars = [b for b in bars if not b.is_remnant]

    nest_pairs_formed = sum(
        1 for b in bars for c in b.cuts if c.nest_role == 'A'
    )
    material_saved = round(sum(
        c.shared_angle_offset_mm for b in bars for c in b.cuts if c.nest_role == 'A'
    ), 2)

    return {
        'bars_needed': len(new_bars),
        'remnant_bars_used': len(bars) - len(new_bars),
        'total_waste_mm': total_waste,
        'efficiency_pct': efficiency,
        'nest_pairs_formed': nest_pairs_formed,
        'material_saved_by_nesting_mm': material_saved,
        'bars': [
            {
                'bar_index': b.bar_index,
                'stock_length_mm': b.stock_length_mm,
                'waste_mm': b.waste_mm,
                'is_remnant': b.is_remnant,
                'stock_bar_id': b.stock_bar_id,
                'cuts': [
                    {
                        'label': c.label,
                        'nominal_mm': c.nominal_mm,
                        'effective_mm': round(c.effective_mm, 2),
                        'offset_mm': c.offset_mm,
                        'job_no': c.job_no,
                        'part_id': c.part_id,
                        'angle_left_deg': c.angle_left_deg,
                        'angle_right_deg': c.angle_right_deg,
                        'profile_height_mm': c.profile_height_mm,
                        'image_no': c.image_no,
                        'is_nest_pair': c.is_nest_pair,
                        'nest_role': c.nest_role,
                        'nested_with_index': c.nested_with_index,
                        'shared_angle_offset_mm': c.shared_angle_offset_mm,
                    }
                    for c in b.cuts
                ],
            }
            for b in bars
        ],
    }
