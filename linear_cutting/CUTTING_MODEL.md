# Linear Cutting — Geometry Model & Data Contract

This document is the single source of truth for how miter (angled) cuts on
pipes/profiles are modelled across backend (`geometry.py`, `optimizer.py`,
`pdf.py`) and frontend (`white-app/manufacturing/linear-cutting/lc-geometry.js`).

## Conventions

Viewed in the **miter plane** (the plane the saw blade swings in):

```
h = H (far edge / "üst")   ┌──────────────────────────┐
                           │           bar            │
h = 0 (near edge / "alt")  └──────────────────────────┘
                           x = 0 ───────────► x = stock_length_mm
```

- `nominal_length_mm` = **long-point (bounding) length**: the finished piece
  measured along the bar at its longest points ("uzun kenardan ölçü").
- `profile_height_mm` (H) = profile dimension inside the miter plane.
  Required whenever an end angle ≠ 0.
- End angles are **signed degrees from square** (0 = square, max ±75):
  - `angle > 0` → far corner (h = H, "üst") is cut back; long point on the
    near edge ("alt uzun").
  - `angle < 0` → near corner cut back; long point on the far edge ("üst uzun").
- Recess depth of the cut-back corner: `t = H · tan(|angle|)`.
- An angled saw pass consumes `kerf / cos(angle)` along the bar axis.

## Shared cuts (nesting)

Right face of piece A and left face of piece B are produced by **one** saw
pass iff `angle_left(B) == -angle_right(A)` and profiles are equal.
Square↔square boundaries always share (the ordinary separating cut).
Parallelogram pieces interlock along the shared diagonal (their bounding
boxes overlap by `t - kerf/cos`).

Pieces with `allow_rotation` may be turned 180° in the miter plane:
`(aL, aR) → (-aR, -aL)`, reported as `flipped: true`. This is how trapezoid
pieces (+45/+45) nest: every other piece is flipped.

## `optimization_result` schema (per group)

```jsonc
{
  "bars_needed": 2,               // new full bars only
  "remnant_bars_used": 1,
  "total_waste_mm": 1234,         // end leftovers
  "efficiency_pct": 91.3,
  "total_pass_count": 14,
  "nest_pairs_formed": 3,         // shared ANGLED boundaries
  "material_saved_by_nesting_mm": 300.0,
  "bars": [{
    "bar_index": 1, "global_bar_index": 1,
    "stock_length_mm": 6000, "used_mm": 5521.2, "waste_mm": 479,
    "is_remnant": false, "stock_bar_id": 0, "shared_cut_count": 5,
    "cuts": [{
      "label": "P1", "part_id": 12, "job_no": "", "image_no": "",
      "nominal_mm": 1000.0,        // long-point length
      "effective_mm": 1000.0,      // legacy alias of nominal_mm
      "offset_mm": 0.0,            // bounding-box start
      "end_mm": 1000.0,            // bounding-box end
      "angle_left_deg": 45.0,      // as-cut (after flip), signed
      "angle_right_deg": -45.0,
      "profile_height_mm": 100.0,
      "flipped": false,
      "requires_bending": false,   // nominal is the developed (flat) length
      "shared_left": false, "shared_right": true
    }],
    "passes": [{
      "seq": 1,
      "x_near_mm": 1000.0,  "x_far_mm": 900.0,   // plane position at h=0 / h=H
      "stop_near_mm": 1000.0, "stop_far_mm": 900.0, // from the fresh edge → what the operator dials
      "angle_deg": -45.0,
      "blade_axial_mm": 4.24,
      "kind": "lead" | "shared" | "end",
      "releases": "P1",            // piece completed by this pass ('' = scrap wedge)
      "long_point": "near" | "far" | "even"  // protruding edge of the REMAINING bar
    }]
  }]
}
```

`LinearCuttingTask` stores one bar: `layout_json` = `cuts`, `passes_json` =
`passes`, plus `is_remnant_bar`.

## Display rules (PDF + web)

- Draw pieces as their true quadrilaterals (near edge at the bottom).
- Shared boundaries: one blade band; unshared: two bands with the scrap
  wedge hatched between them. End leftover hatched grey.
- Mark flipped pieces (web: `↻`; PDF: letter `d` after the piece index — the
  embedded Vera font lacks the arrow glyph) and bending pieces (web: badge;
  PDF: letter `b`), with a legend explaining the letters.
- Angle wording for humans: positive → "alt uzun" (long point on bottom
  edge), negative → "üst uzun".
- The pass table is the operator contract: for each pass show angle,
  stop_near/stop_far (mm) and which piece comes off. Stops are measured
  from the fresh cut edge of the remaining bar, so they can be dialled
  directly on a length stop.
