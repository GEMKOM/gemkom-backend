"""
Linear Cutting Optimizer — 1-D packing with miter-cut awareness.

Model (full derivation in ``geometry.py``):

* ``nominal_length_mm`` is a piece's LONG-POINT (bounding) length along the
  bar — what a tape measure reads across the finished piece at its longest.
* End angles are signed degrees from square; the sign says which corner is
  cut back (positive = far edge recessed, negative = near edge recessed).
* Consecutive pieces whose touching faces lie in one plane
  (``angle_left(B) == -angle_right(A)``) are separated by a SINGLE saw pass
  consuming ``kerf / cos(angle)`` — this is how two parallelogram pieces
  interlock along one diagonal.  Faces that are not coplanar each get their
  own pass and the wedge between them becomes scrap; the required gap comes
  from ``geometry.boundary_gap_mm``.
* Pieces may be turned 180° in the miter plane (``allow_rotation``), which
  maps ``(aL, aR) → (-aR, -aL)`` — the optimizer uses this to create shared
  cuts (e.g. trapezoid pieces nested tip-to-tail alternately flipped).

Packing: pieces are packed by several deterministic strategies
(order × placement policy); the best complete solution wins
(fewest new bars, then fewest remnants, least waste, fewest saw passes).
"""

from dataclasses import dataclass, replace
from typing import List, Optional

from .geometry import (
    ANGLE_TOL_DEG,
    boundary_gap_mm,
    kerf_axial_mm,
    passes_for_bar,
    recess_mm,
    rotated_angles,
    validate_piece,
)

_EPS = 1e-6


@dataclass(frozen=True)
class Piece:
    """A single physical piece to cut, in a fixed orientation."""
    label: str
    part_id: int
    job_no: str
    image_no: str
    length: float
    ang_l: float
    ang_r: float
    height: float
    allow_rotation: bool = True
    requires_bending: bool = False
    seq: int = 0            # stable identity for deterministic sorts
    flipped: bool = False

    def rotated(self) -> 'Piece':
        al, ar = rotated_angles(self.ang_l, self.ang_r)
        return replace(self, ang_l=al, ang_r=ar, flipped=not self.flipped)

    def orientations(self):
        yield self
        if self.allow_rotation:
            r = self.rotated()
            if (abs(r.ang_l - self.ang_l) > ANGLE_TOL_DEG
                    or abs(r.ang_r - self.ang_r) > ANGLE_TOL_DEG):
                yield r


class _BarState:
    __slots__ = ('stock_length', 'is_remnant', 'stock_bar_id',
                 'placements', 'cursor_end', 'shared_count', 'saved_mm')

    def __init__(self, stock_length: float, is_remnant: bool = False,
                 stock_bar_id: int = 0):
        self.stock_length = float(stock_length)
        self.is_remnant = is_remnant
        self.stock_bar_id = stock_bar_id
        self.placements = []        # list of (piece, offset, shared_with_prev)
        self.cursor_end = 0.0       # bounding-box end of the last piece
        self.shared_count = 0       # shared (single-pass) boundaries
        self.saved_mm = 0.0         # interlock overlap reclaimed by sharing

    @property
    def leftover(self) -> float:
        return self.stock_length - self.cursor_end


@dataclass(frozen=True)
class _Candidate:
    end: float
    gap: float
    shared: bool
    orient: Piece
    offset: float


def _candidate_for(bar: _BarState, piece: Piece, kerf: float) -> Optional[_Candidate]:
    """Best feasible way to append ``piece`` to ``bar`` (or None)."""
    best = None
    for orient in piece.orientations():
        if not bar.placements:
            # Fresh factory end is trusted on new bars; remnant ends are not,
            # so the first pass on a remnant gets a full blade of clearance.
            lead = kerf_axial_mm(kerf, orient.ang_l) if bar.is_remnant else 0.0
            offset, gap, shared = lead, lead, False
        else:
            last = bar.placements[-1][0]
            gap, shared = boundary_gap_mm(
                last.ang_r, orient.ang_l, last.height, orient.height, kerf)
            offset = bar.cursor_end + gap
        end = offset + orient.length
        if end > bar.stock_length + _EPS:
            continue
        cand = _Candidate(end=end, gap=gap, shared=shared,
                          orient=orient, offset=offset)
        if best is None or (cand.end, not cand.shared, cand.orient.flipped) < \
                           (best.end, not best.shared, best.orient.flipped):
            best = cand
    return best


def _place(bar: _BarState, cand: _Candidate, kerf: float):
    bar.placements.append((cand.orient, cand.offset, cand.shared))
    bar.cursor_end = cand.end
    if cand.shared and bar.placements[-2:]:
        bar.shared_count += 1
        clearance = kerf_axial_mm(kerf, cand.orient.ang_l)
        bar.saved_mm += max(0.0, clearance - cand.gap)


def _pack(pieces: List[Piece], stock_length: float, kerf: float,
          stock_seed: list, policy: str) -> Optional[List[_BarState]]:
    bars = [
        _BarState(s['length_mm'], is_remnant=True, stock_bar_id=s['id'])
        for s in stock_seed
    ]
    for piece in pieces:
        chosen = None       # (sort_key, bar, candidate)
        for idx, bar in enumerate(bars):
            cand = _candidate_for(bar, piece, kerf)
            if cand is None:
                continue
            if policy == 'first':
                chosen = (idx, bar, cand)
                break
            elif policy == 'best_end':
                key = (bar.stock_length - cand.end, idx)
            else:  # 'best_gap'
                key = (cand.gap, bar.stock_length - cand.end, idx)
            if chosen is None or key < chosen[0]:
                chosen = (key, bar, cand)
        if chosen is None:
            new_bar = _BarState(stock_length, is_remnant=False)
            cand = _candidate_for(new_bar, piece, kerf)
            if cand is None:
                return None     # cannot place even on a fresh bar
            bars.append(new_bar)
            chosen = (None, new_bar, cand)
        _place(chosen[1], chosen[2], kerf)
    return [b for b in bars if b.placements or not b.is_remnant]


def _light_settings(bar: _BarState):
    """(setup_changes, pass_count) computed arithmetically from placements —
    mirrors passes_for_bar's pass sequence without building any dicts.
    A saw setting is (|angle| rounded to 0.1°, physical lean of the plane).
    """
    def setting(ang, side):
        if abs(ang) <= ANGLE_TOL_DEG:
            return (0.0, 0)
        if side == 'left':
            lean = 1 if ang > 0 else -1
        else:
            lean = -1 if ang > 0 else 1
        return (round(abs(ang), 1), lean)

    settings = []
    placements = bar.placements
    first = placements[0][0]
    if bar.is_remnant or abs(first.ang_l) > ANGLE_TOL_DEG:
        settings.append(setting(first.ang_l, 'left'))
    for i, (orient, _, _) in enumerate(placements):
        is_last = (i == len(placements) - 1)
        if is_last:
            flush = (not bar.is_remnant
                     and abs(orient.ang_r) <= ANGLE_TOL_DEG
                     and abs(bar.cursor_end - bar.stock_length) < 0.05)
            if not flush:
                settings.append(setting(orient.ang_r, 'right'))
        elif placements[i + 1][2]:          # next piece shares this cut
            settings.append(setting(orient.ang_r, 'right'))
        else:
            settings.append(setting(orient.ang_r, 'right'))
            settings.append(setting(placements[i + 1][0].ang_l, 'left'))
    changes = sum(1 for a, b in zip(settings, settings[1:]) if a != b)
    return changes, len(settings)


def _bar_cost(bar: _BarState):
    """Per-bar objective, aligned with the global score: consumed span in
    1 cm buckets (less span = less kerf/wedge loss), then saw settings,
    then pass count, then exact span."""
    changes, pass_count = _light_settings(bar)
    return (
        round(bar.cursor_end / 10.0),
        changes,
        pass_count,
        round(bar.cursor_end, 2),
    )


def _try_order(order: List[Piece], stock_length: float, is_remnant: bool,
               stock_bar_id: int, kerf: float) -> Optional[_BarState]:
    """Re-place the given pieces on a fresh bar in this exact order
    (orientation re-chosen per boundary). None if the order doesn't fit."""
    bar = _BarState(stock_length, is_remnant, stock_bar_id)
    for piece in order:
        cand = _candidate_for(bar, piece, kerf)
        if cand is None:
            return None
        _place(bar, cand, kerf)
    return bar


def _piece_key(p: Piece):
    """Interchangeability key: pieces of the same part are identical for
    arrangement purposes (orientation is re-chosen at placement time)."""
    return (p.part_id, p.label, round(p.length, 2), p.height,
            round(min((p.ang_l, p.ang_r), (-p.ang_r, -p.ang_l))[0], 2),
            round(min((p.ang_l, p.ang_r), (-p.ang_r, -p.ang_l))[1], 2),
            p.allow_rotation, p.requires_bending)


# Hard cap on candidate-order evaluations per bar — the neighborhood is
# deduplicated by arrangement signature, so this is rarely reached; it
# bounds the worst case deterministically.
_MAX_REORDER_EVALS = 240


def _improve_bar(bar: _BarState, kerf: float) -> _BarState:
    """Within-bar local search: greedy packing appends pieces in a global
    order and never reconsiders their arrangement on the bar, which can
    leave e.g. a square piece stranded after an angled chain (an extra
    wedge cut plus an extra saw setting).  Hill-climb over move-to-position
    reorderings of this bar's own pieces, keeping strict improvements.

    Identical pieces make most moves no-ops, so candidate orders are
    deduplicated by their piece-key signature before any rebuild."""
    if len(bar.placements) < 2:
        return bar
    # All-square bars are order-invariant for cost — skip the work.
    if all(abs(o.ang_l) <= ANGLE_TOL_DEG and abs(o.ang_r) <= ANGLE_TOL_DEG
           for o, _, _ in bar.placements):
        return bar
    keys0 = [_piece_key(o) for o, _, _ in bar.placements]
    if len(set(keys0)) == 1:
        return bar          # all pieces interchangeable — nothing to reorder

    best, best_cost = bar, _bar_cost(bar)
    seen = {tuple(keys0)}
    evals = 0
    for _ in range(4):
        improved = False
        pieces = [o for o, _, _ in best.placements]
        keys = [_piece_key(o) for o in pieces]
        n = len(pieces)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                order_keys = keys.copy()
                moved_key = order_keys.pop(i)
                order_keys.insert(j, moved_key)
                sig = tuple(order_keys)
                if sig in seen:
                    continue
                seen.add(sig)
                evals += 1
                if evals > _MAX_REORDER_EVALS:
                    return best
                order = pieces.copy()
                moved = order.pop(i)
                order.insert(j, moved)
                cand = _try_order(order, best.stock_length, best.is_remnant,
                                  best.stock_bar_id, kerf)
                if cand is None:
                    continue
                cost = _bar_cost(cand)
                if cost < best_cost:
                    best, best_cost = cand, cost
                    improved = True
        if not improved:
            break
    return best


def _build_pieces(parts_data: list) -> List[Piece]:
    pieces: List[Piece] = []
    problems: List[str] = []
    seq = 0
    for p in parts_data:
        label = p.get('label', '') or ''
        length = float(p.get('nominal_length_mm') or 0)
        ang_l = float(p.get('angle_left_deg') or 0)
        ang_r = float(p.get('angle_right_deg') or 0)
        height = float(p.get('profile_height_mm') or 0)
        problems.extend(validate_piece(label, length, ang_l, ang_r, height))
        qty = int(p.get('quantity') or 0)
        for _ in range(max(0, qty)):
            seq += 1
            pieces.append(Piece(
                label=label,
                part_id=int(p.get('id') or 0),
                job_no=p.get('job_no', '') or '',
                image_no=p.get('image_no', '') or '',
                length=length,
                ang_l=ang_l,
                ang_r=ang_r,
                height=height,
                allow_rotation=bool(p.get('allow_rotation', True)),
                requires_bending=bool(p.get('requires_bending', False)),
                seq=seq,
            ))
    if problems:
        raise ValueError(' '.join(problems))
    return pieces


def _orders(pieces: List[Piece], stock_length: float):
    """Deterministic piece orders to try.  Oversize pieces (longer than a
    fresh bar — they can only live on long remnants) always go first."""
    def ovs(p):
        return 0 if p.length > stock_length else 1

    by_len = sorted(pieces, key=lambda p: (ovs(p), -p.length, p.seq))
    by_angle = sorted(pieces, key=lambda p: (
        ovs(p),
        -max(abs(p.ang_l), abs(p.ang_r)),
        -min(abs(p.ang_l), abs(p.ang_r)),
        -p.length, p.seq))
    by_job = sorted(pieces, key=lambda p: (ovs(p), p.job_no, -p.length, p.seq))
    return [('len_desc', by_len), ('angle_family', by_angle), ('job', by_job)]


def _saw_setup_changes(passes: list) -> int:
    """How many times the operator must change the saw setting on this bar.

    A 'setting' is the blade's magnitude + physical lean direction (the side
    the cut plane leans toward at the far edge) — two passes at |45°| with
    the same lean are one setting even if the pieces' signed angles differ.
    """
    changes = 0
    prev = None
    for p in passes:
        ang = abs(float(p.get('angle_deg') or 0))
        if ang < ANGLE_TOL_DEG:
            setting = (0.0, 0)
        else:
            lean = 1 if float(p['x_far_mm']) > float(p['x_near_mm']) else -1
            setting = (round(ang, 1), lean)
        if prev is not None and setting != prev:
            changes += 1
        prev = setting
    return changes


def _solution_dict(bars: List[_BarState], stock_length: float, kerf: float) -> dict:
    bars_out = []
    total_piece_mm = 0.0
    for i, bar in enumerate(bars, start=1):
        cuts = []
        for j, (orient, offset, shared) in enumerate(bar.placements):
            # True material content of the piece (area / profile height):
            # long-point length minus half of each end recess.  Using the
            # bounding length here would double-count interlocked diagonals
            # and push efficiency above 100 %.
            total_piece_mm += orient.length - (
                recess_mm(orient.ang_l, orient.height)
                + recess_mm(orient.ang_r, orient.height)
            ) / 2.0
            # Full-precision values first — passes are derived from these;
            # rounding happens only on the way out.
            cut = {
                'label': orient.label,
                'nominal_mm': orient.length,
                'effective_mm': orient.length,   # back-compat
                'offset_mm': offset,
                'end_mm': offset + orient.length,
                'job_no': orient.job_no,
                'part_id': orient.part_id,
                'image_no': orient.image_no,
                'angle_left_deg': round(orient.ang_l, 2),
                'angle_right_deg': round(orient.ang_r, 2),
                'profile_height_mm': round(orient.height, 1),
                'flipped': orient.flipped,
                'requires_bending': orient.requires_bending,
                'shared_left': shared,
                'shared_right': False,
            }
            if shared and cuts:
                cuts[-1]['shared_right'] = True
            cuts.append(cut)
        bar_dict = {
            'bar_index': i,
            'stock_length_mm': int(round(bar.stock_length)),
            'used_mm': round(bar.cursor_end, 1),
            'waste_mm': int(round(max(0.0, bar.leftover))),
            'is_remnant': bar.is_remnant,
            'stock_bar_id': bar.stock_bar_id,
            'shared_cut_count': bar.shared_count,
            'cuts': cuts,
        }
        bar_dict['passes'] = passes_for_bar(bar_dict, kerf)
        bar_dict['saw_setup_changes'] = _saw_setup_changes(bar_dict['passes'])
        for c in cuts:
            c['nominal_mm'] = round(c['nominal_mm'], 1)
            c['effective_mm'] = round(c['effective_mm'], 1)
            c['offset_mm'] = round(c['offset_mm'], 1)
            c['end_mm'] = round(c['end_mm'], 1)
        bars_out.append(bar_dict)

    new_bars = [b for b in bars_out if not b['is_remnant']]
    total_stock = sum(b['stock_length_mm'] for b in bars_out)
    total_waste = sum(b['waste_mm'] for b in bars_out)
    efficiency = round(total_piece_mm / total_stock * 100, 2) if total_stock else 100.0
    shared_angled = sum(
        1 for b in bars_out for c in b['cuts']
        if c['shared_left'] and abs(c['angle_left_deg']) > ANGLE_TOL_DEG
    )
    return {
        'bars_needed': len(new_bars),
        'remnant_bars_used': len(bars_out) - len(new_bars),
        'total_waste_mm': total_waste,
        'efficiency_pct': efficiency,
        'total_pass_count': sum(len(b['passes']) for b in bars_out),
        'saw_setup_changes': sum(b['saw_setup_changes'] for b in bars_out),
        'nest_pairs_formed': shared_angled,
        'material_saved_by_nesting_mm': round(sum(b.saved_mm for b in bars), 2),
        'bars': bars_out,
    }


def optimize(
    parts_data: list,
    stock_length_mm: int,
    kerf_mm: float = 3.0,
    stock_pieces: list = None,
) -> dict:
    """
    Compute an optimized cutting layout.

    Parameters
    ----------
    parts_data : list of dicts with keys
        label, nominal_length_mm (long-point length), quantity,
        angle_left_deg, angle_right_deg (signed, 0 = square),
        profile_height_mm, job_no?, id?, image_no?,
        allow_rotation? (default True), requires_bending? (default False)
    stock_length_mm : length of a fresh stock bar
    kerf_mm : blade thickness (perpendicular to the blade)
    stock_pieces : optional remnant/warehouse pieces to use before opening
        fresh bars — dicts of {id, length_mm, quantity}

    Returns a dict: bars_needed, remnant_bars_used, total_waste_mm,
    efficiency_pct, total_pass_count, nest_pairs_formed,
    material_saved_by_nesting_mm, bars: [...].  Each bar carries its
    ``cuts`` (placed pieces) and ``passes`` (ordered saw passes with
    operator stop distances).

    Raises ``ValueError`` for invalid parts or pieces that fit nowhere.
    """
    stock_length = float(stock_length_mm)
    kerf = float(kerf_mm)
    pieces = _build_pieces(parts_data)

    if not pieces:
        return {
            'bars_needed': 0,
            'remnant_bars_used': 0,
            'total_waste_mm': 0,
            'efficiency_pct': 100.0,
            'total_pass_count': 0,
            'nest_pairs_formed': 0,
            'material_saved_by_nesting_mm': 0.0,
            'bars': [],
        }

    # Expand remnant stock into individual seed bars, longest first.
    stock_seed = []
    for piece in sorted(stock_pieces or [], key=lambda s: -float(s['length_mm'])):
        for _ in range(int(piece.get('quantity') or 0)):
            stock_seed.append({
                'length_mm': float(piece['length_mm']),
                'id': int(piece.get('id') or 0),
            })

    # Feasibility: every piece must fit a fresh bar or at least one remnant
    # (in either orientation — remnant lead trim depends on the lead angle).
    max_remnant = max((s['length_mm'] for s in stock_seed), default=0.0)
    for p in pieces:
        fits_new = p.length <= stock_length + _EPS
        lead = min(kerf_axial_mm(kerf, o.ang_l) for o in p.orientations())
        fits_remnant = p.length + lead <= max_remnant + _EPS
        if not fits_new and not fits_remnant:
            raise ValueError(
                f"'{p.label}' parçası ({p.length:g} mm) {stock_length_mm:g} mm "
                f"stok boyuna sığmıyor."
            )

    best = None
    for _, ordered in _orders(pieces, stock_length):
        for policy in ('first', 'best_end', 'best_gap'):
            bars = _pack(ordered, stock_length, kerf, stock_seed, policy)
            if bars is None:
                continue
            bars = [_improve_bar(b, kerf) for b in bars]
            solution = _solution_dict(bars, stock_length, kerf)
            # Material first (user priority #1), then cutting easiness
            # (priority #2).  With the bar count fixed, the material metric
            # is the CONSUMED SPAN (piece material is constant, so a smaller
            # span means less kerf/wedge loss and a larger usable tail —
            # minimizing leftover would reward the opposite).  Compared in
            # 1 cm buckets so sub-centimeter noise never outvotes an extra
            # saw-angle setting change; exact span is a later tie-break to
            # stay deterministic.
            total_used = round(sum(b['used_mm'] for b in solution['bars']), 1)
            score = (
                solution['bars_needed'],
                solution['remnant_bars_used'],
                round(total_used / 10.0),
                solution['saw_setup_changes'],
                solution['total_pass_count'],
                total_used,
                -max((b['waste_mm'] for b in solution['bars']), default=0),
            )
            if best is None or score < best[0]:
                best = (score, solution)

    if best is None:
        # Only possible when an oversize piece lost its remnant to greedy
        # packing in every strategy.
        raise ValueError(
            'Parçalar mevcut stok barlara yerleştirilemedi. '
            'Stok boyundan uzun parçalar için yeterli uzunlukta stok bar girin.'
        )
    return best[1]
