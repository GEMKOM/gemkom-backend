"""
Miter-cut geometry for linear (1-D) cutting of prismatic stock — pipes,
tubes, profiles.

Every function here is pure (no Django imports) so the whole model is unit
testable and reusable from the optimizer, the PDF renderer and (conceptually)
the frontend, which mirrors these formulas in JS.

Coordinate system & conventions
===============================
We look at the bar in the *miter plane* (the plane the saw blade swings in):

    h = H  (far edge)   ┌────────────────────────┐
                        │           bar          │
    h = 0  (near edge)  └────────────────────────┘
                        x = 0  ──────────────►  x = stock_length

* ``x`` runs along the bar axis, ``h`` across the profile inside the miter
  plane.  ``H`` (``profile_height_mm``) is the profile's dimension in that
  plane (for a horizontal-swing saw with the profile laid flat this is the
  profile's *width* in plan view; for a vertical bevel it is its height).

* ``nominal_length_mm`` of a piece is its **long-point (bounding) length**:
  the distance between its two most extreme points measured along the bar.
  This is what a tape measure reads across the finished piece at its longest.

* End angles are degrees from square (0 = straight cut), **signed**:

    - ``angle > 0``  →  the FAR corner (h = H) is cut back / recessed;
                        the long point sits on the NEAR edge (h = 0).
    - ``angle < 0``  →  the NEAR corner (h = 0) is recessed;
                        the long point sits on the FAR edge (h = H).

  The recess depth at the cut-back corner is ``t = H * tan(|angle|)``.

* A piece is described by ``(length, angle_left, angle_right, H)``.  Its
  *bounding box* on the bar is ``[offset, offset + length]``; the angled
  faces live inside that box.

Shared cuts (nesting)
=====================
The right face of piece A and the left face of piece B lie in one plane —
and can therefore be produced with a single saw pass — iff the faces are
parallel and the profiles equal::

    angle_left(B) == -angle_right(A)     (and  H_A == H_B)

(For square ends, 0 == -0: consecutive square pieces always share their
separating cut — that is the ordinary case.)

Kerf
====
The blade removes ``kerf_mm`` measured perpendicular to the blade.  Along
the bar axis an angled pass therefore consumes ``kerf / cos(angle)``.

Boundary gap formula
====================
Let ``a(h)`` be the recess profile of A's right face (distance from A's
bounding-box end to the face, at height h) and ``b(h)`` that of B's left
face.  Both are linear in h, so with a gap ``g`` between the bounding boxes
the face-to-face distance is ``D(h) = g + a(h) + b(h)`` and its minimum is
attained at h = 0 or h = H.

* Shared cut: faces parallel, one pass →  ``D(h) == kerf/cos`` for all h.
* Separate passes: each blade band must clear the *other* piece →
  ``min D(h) >= max(kerf/cos(a), kerf/cos(b))``.

Therefore::

    g = clearance - min(a(0) + b(0),  a(H) + b(H))

``g`` may be negative — the bounding boxes then interlock (this is exactly
how two parallelograms share one diagonal cut).
"""

import math

# Angles closer than this are considered equal (deg)
ANGLE_TOL_DEG = 0.05
# Profile heights closer than this are considered equal (mm)
HEIGHT_TOL_MM = 0.5
# Sanity cap — tan() explodes beyond this and no saw cuts steeper miters
MAX_ANGLE_DEG = 75.0
# Generic length epsilon (mm)
EPS_MM = 1e-6


def recess_mm(angle_deg: float, height_mm: float) -> float:
    """Axial depth of the cut-back corner for a miter at ``angle_deg``."""
    a = abs(float(angle_deg))
    if a < ANGLE_TOL_DEG or height_mm <= 0:
        return 0.0
    return float(height_mm) * math.tan(math.radians(a))


def kerf_axial_mm(kerf_mm: float, angle_deg: float) -> float:
    """Blade consumption measured along the bar axis for one pass."""
    a = abs(float(angle_deg))
    if a < ANGLE_TOL_DEG:
        return float(kerf_mm)
    return float(kerf_mm) / math.cos(math.radians(a))


def end_recess_profile(angle_deg: float, height_mm: float):
    """
    Recess of an end face at the two extreme heights.

    Returns ``(recess_at_near, recess_at_far)`` where *near* is h = 0 and
    *far* is h = H.  Identical formula for left and right ends: a positive
    angle recesses the far corner, a negative one the near corner.
    """
    t = recess_mm(angle_deg, height_mm)
    if t == 0.0:
        return 0.0, 0.0
    if float(angle_deg) > 0:
        return 0.0, t
    return t, 0.0


def angles_shareable(angle_right_a: float, angle_left_b: float,
                     height_a: float, height_b: float) -> bool:
    """One saw pass can produce A's right face and B's left face."""
    a_square = abs(float(angle_right_a)) <= ANGLE_TOL_DEG
    b_square = abs(float(angle_left_b)) <= ANGLE_TOL_DEG
    if a_square and b_square:
        # A square pass is a perpendicular plane through the whole
        # cross-section — profile height is irrelevant to sharing it.
        return True
    if abs(float(height_a) - float(height_b)) > HEIGHT_TOL_MM:
        return False
    return abs(float(angle_right_a) + float(angle_left_b)) <= ANGLE_TOL_DEG


def boundary_gap_mm(angle_right_a: float, angle_left_b: float,
                    height_a: float, height_b: float, kerf_mm: float):
    """
    Minimal gap between the bounding boxes of two consecutive pieces.

    Returns ``(gap_mm, shared)``.  ``gap_mm`` may be negative (interlock).
    """
    shared = angles_shareable(angle_right_a, angle_left_b, height_a, height_b)
    a_near, a_far = end_recess_profile(angle_right_a, height_a)
    b_near, b_far = end_recess_profile(angle_left_b, height_b)
    if shared:
        clearance = kerf_axial_mm(kerf_mm, angle_right_a)
    else:
        clearance = max(
            kerf_axial_mm(kerf_mm, angle_right_a),
            kerf_axial_mm(kerf_mm, angle_left_b),
        )
    gap = clearance - min(a_near + b_near, a_far + b_far)
    return gap, shared


def rotated_angles(angle_left: float, angle_right: float):
    """
    End angles after turning the piece 180° in the miter plane
    (left end becomes right end, leans mirror).
    """
    return -float(angle_right), -float(angle_left)


def piece_faces(offset_mm: float, length_mm: float,
                angle_left: float, angle_right: float, height_mm: float):
    """
    Absolute face segments of a placed piece.

    Returns ``{'left': (x_near, x_far), 'right': (x_near, x_far)}`` where
    *near* is the h = 0 edge and *far* the h = H edge.
    """
    l_near, l_far = end_recess_profile(angle_left, height_mm)
    r_near, r_far = end_recess_profile(angle_right, height_mm)
    end = offset_mm + length_mm
    return {
        'left':  (offset_mm + l_near, offset_mm + l_far),
        'right': (end - r_near, end - r_far),
    }


def validate_piece(label: str, length_mm: float, angle_left: float,
                   angle_right: float, height_mm: float) -> list:
    """Return a list of human-readable problems with a part definition."""
    problems = []
    if not length_mm or length_mm <= 0:
        problems.append(f"'{label}': uzunluk sıfırdan büyük olmalı.")
    for side, ang in (('sol', angle_left), ('sağ', angle_right)):
        if abs(float(ang)) > MAX_ANGLE_DEG:
            problems.append(
                f"'{label}': {side} açı {ang}° — en fazla ±{MAX_ANGLE_DEG:g}° desteklenir."
            )
    has_angle = abs(float(angle_left)) > ANGLE_TOL_DEG or abs(float(angle_right)) > ANGLE_TOL_DEG
    if has_angle and (not height_mm or height_mm <= 0):
        problems.append(
            f"'{label}': açılı kesim için profil ölçüsü (açı düzlemindeki kesit boyu) girilmelidir."
        )
    elif not problems and length_mm and length_mm > 0:
        # The two faces must not cross inside the profile: the edge length
        # at both extreme heights has to stay non-negative.
        l_near, l_far = end_recess_profile(angle_left, height_mm or 0)
        r_near, r_far = end_recess_profile(angle_right, height_mm or 0)
        if (length_mm - (l_near + r_near) < -EPS_MM
                or length_mm - (l_far + r_far) < -EPS_MM):
            problems.append(
                f"'{label}': açılar ve profil ölçüsüne göre bu boy imkansız — "
                f"kesim yüzeyleri kesişiyor. Boyu uzatın veya açı/profil ölçüsünü küçültün."
            )
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# Saw-pass generation
# ─────────────────────────────────────────────────────────────────────────────

def passes_for_bar(bar: dict, kerf_mm: float) -> list:
    """
    Derive the ordered list of saw passes for one bar layout.

    ``bar`` must carry ``stock_length_mm``, ``is_remnant`` and ``cuts``;
    each cut needs ``offset_mm``, ``nominal_mm``, ``angle_left_deg``,
    ``angle_right_deg``, ``profile_height_mm``, ``shared_right`` and
    ``label``.

    Each pass dict::

        {
          'seq': 1-based order,
          'x_near_mm' / 'x_far_mm': absolute plane position at the near/far
              edge, measured from the ORIGINAL bar start,
          'stop_near_mm' / 'stop_far_mm': distance from the previous pass
              (or bar start) — what the operator dials on the length stop,
          'angle_deg': signed face angle (0 = square),
          'blade_axial_mm': kerf consumption along the axis,
          'kind': 'lead' | 'shared' | 'end',
          'releases': label of the piece completed by this pass ('' if the
              pass only frees a scrap wedge),
          'long_point': after this pass, which edge of the REMAINING bar
              protrudes: 'near' | 'far' | 'even'.
        }
    """
    cuts = bar.get('cuts') or []
    if not cuts:
        return []
    stock = float(bar.get('stock_length_mm') or 0)
    is_remnant = bool(bar.get('is_remnant'))

    def _face(cut, side):
        return piece_faces(
            float(cut['offset_mm']), float(cut['nominal_mm']),
            float(cut.get('angle_left_deg') or 0),
            float(cut.get('angle_right_deg') or 0),
            float(cut.get('profile_height_mm') or 0),
        )[side]

    raw = []

    first = cuts[0]
    first_al = float(first.get('angle_left_deg') or 0)
    if is_remnant or abs(first_al) > ANGLE_TOL_DEG:
        near, far = _face(first, 'left')
        raw.append({
            'x_near_mm': near, 'x_far_mm': far,
            'angle_deg': first_al,
            'kind': 'lead',
            'releases': '',
        })

    for i, cut in enumerate(cuts):
        ar = float(cut.get('angle_right_deg') or 0)
        near, far = _face(cut, 'right')
        is_last = (i == len(cuts) - 1)
        if is_last:
            end = float(cut['offset_mm']) + float(cut['nominal_mm'])
            # A square face flush with the factory end of a fresh bar needs
            # no separating pass — the bar end IS the face.
            if (not is_remnant and abs(ar) <= ANGLE_TOL_DEG
                    and abs(end - stock) < 0.05):
                continue
            raw.append({
                'x_near_mm': near, 'x_far_mm': far,
                'angle_deg': ar, 'kind': 'end',
                'releases': cut.get('label', ''),
            })
        elif cut.get('shared_right'):
            raw.append({
                'x_near_mm': near, 'x_far_mm': far,
                'angle_deg': ar, 'kind': 'shared',
                'releases': cut.get('label', ''),
            })
        else:
            nxt = cuts[i + 1]
            raw.append({
                'x_near_mm': near, 'x_far_mm': far,
                'angle_deg': ar, 'kind': 'end',
                'releases': cut.get('label', ''),
            })
            n_near, n_far = _face(nxt, 'left')
            raw.append({
                'x_near_mm': n_near, 'x_far_mm': n_far,
                'angle_deg': float(nxt.get('angle_left_deg') or 0),
                'kind': 'lead',
                'releases': '',   # frees the scrap wedge between the faces
            })

    raw.sort(key=lambda p: (p['x_near_mm'] + p['x_far_mm']) / 2.0)

    # Stop distances are measured from the REMAINING bar's fresh leading
    # edge.  A 'shared'/'end' pass leaves its blade band on the right of the
    # marked plane (the remaining bar starts one blade-width later); a
    # 'lead' pass leaves the band on the left (the remaining bar starts at
    # the marked plane itself).
    passes = []
    prev_edge_near, prev_edge_far = 0.0, 0.0
    for seq, p in enumerate(raw, start=1):
        ang = p['angle_deg']
        blade = kerf_axial_mm(kerf_mm, ang)
        if abs(ang) <= ANGLE_TOL_DEG:
            long_point = 'even'
        else:
            # For 'shared'/'end' passes the remaining bar lies BEYOND the
            # blade band, on the opposite side of the plane from the face's
            # owner: angle > 0 (owner's far corner recessed) leaves the
            # remaining bar protruding on the far edge.  For a 'lead' pass
            # the remaining bar IS the face's owner, which flips the map.
            protrudes_far = ang > 0
            if p['kind'] == 'lead':
                protrudes_far = not protrudes_far
            long_point = 'far' if protrudes_far else 'near'
        def _clean(v):
            # Kill float noise: sub-0.05 mm magnitudes (incl. -0.0) become 0,
            # and small negative artifacts of pre-rounded inputs clamp to 0
            # (a real geometry error would be far larger than 0.2 mm).
            r = round(v, 1)
            if abs(r) < 0.05 or -0.2 <= r < 0:
                return 0.0
            return r
        passes.append({
            'seq': seq,
            'x_near_mm': _clean(p['x_near_mm']),
            'x_far_mm': _clean(p['x_far_mm']),
            'stop_near_mm': _clean(p['x_near_mm'] - prev_edge_near),
            'stop_far_mm': _clean(p['x_far_mm'] - prev_edge_far),
            'angle_deg': round(ang, 2),
            'blade_axial_mm': round(blade, 2),
            'kind': p['kind'],
            'releases': p['releases'],
            'long_point': long_point,
        })
        if p['kind'] == 'lead':
            prev_edge_near, prev_edge_far = p['x_near_mm'], p['x_far_mm']
        else:
            prev_edge_near = p['x_near_mm'] + blade
            prev_edge_far = p['x_far_mm'] + blade
    return passes
