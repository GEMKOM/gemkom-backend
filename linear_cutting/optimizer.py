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


@dataclass
class Bar:
    """One stock bar with its placed cuts."""
    bar_index: int
    stock_length_mm: int
    cuts: List[PlacedCut] = field(default_factory=list)
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
        )
        self._used_mm += part.effective_mm + kerf_mm
        self.cuts.append(cut)
        return cut

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
            ))
    return instances


def optimize(
    parts_data: list,
    stock_length_mm: int,
    kerf_mm: float = 3.0,
) -> dict:
    """
    Run First Fit Decreasing (FFD) bin-packing on the given parts.

    Parameters
    ----------
    parts_data : list of dicts
        Each dict: {label, nominal_length_mm, quantity, angle_left_deg,
                    angle_right_deg, profile_height_mm, job_no?, id?}
    stock_length_mm : int
        Length of a single stock bar in mm.
    kerf_mm : float
        Blade kerf in mm (material removed per cut).

    Returns
    -------
    dict with keys:
        bars_needed, total_waste_mm, efficiency_pct, bars (list)

    Raises
    ------
    ValueError
        If any single part's effective length exceeds the stock bar length.
    """
    instances = _build_instances(parts_data)

    # Validate: no part can exceed the bar
    for inst in instances:
        if inst.effective_mm > stock_length_mm:
            raise ValueError(
                f"Part '{inst.label}' has effective length {inst.effective_mm:.1f} mm "
                f"which exceeds the stock bar length of {stock_length_mm} mm."
            )

    if not instances:
        return {
            'bars_needed': 0,
            'total_waste_mm': 0,
            'efficiency_pct': 100.0,
            'bars': [],
        }

    # Sort descending by effective length (FFD heuristic)
    instances.sort(key=lambda p: p.effective_mm, reverse=True)

    bars: List[Bar] = []

    for inst in instances:
        placed = False
        for bar in bars:
            if bar.can_fit(inst.effective_mm, kerf_mm):
                bar.place(inst, kerf_mm)
                placed = True
                break
        if not placed:
            new_bar = Bar(bar_index=len(bars) + 1, stock_length_mm=stock_length_mm)
            new_bar.place(inst, kerf_mm)
            bars.append(new_bar)

    total_waste = sum(b.waste_mm for b in bars)
    total_material = stock_length_mm * len(bars)
    efficiency = round((1 - total_waste / total_material) * 100, 2) if total_material else 0.0

    return {
        'bars_needed': len(bars),
        'total_waste_mm': total_waste,
        'efficiency_pct': efficiency,
        'bars': [
            {
                'bar_index': b.bar_index,
                'stock_length_mm': b.stock_length_mm,
                'waste_mm': b.waste_mm,
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
                    }
                    for c in b.cuts
                ],
            }
            for b in bars
        ],
    }
