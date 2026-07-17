"""
Unit tests for the linear cutting geometry core and optimizer.

Pure-python (no DB): run with
    python -m unittest linear_cutting.tests -v
"""

import math
import unittest

from .geometry import (
    boundary_gap_mm,
    end_recess_profile,
    kerf_axial_mm,
    piece_faces,
    recess_mm,
)
from .optimizer import optimize


def part(label, length, qty=1, al=0, ar=0, h=0, **kw):
    d = {
        'id': kw.pop('id', 0),
        'label': label,
        'nominal_length_mm': length,
        'quantity': qty,
        'angle_left_deg': al,
        'angle_right_deg': ar,
        'profile_height_mm': h,
        'job_no': kw.pop('job_no', ''),
        'image_no': '',
    }
    d.update(kw)
    return d


def all_cuts(result):
    return [c for b in result['bars'] for c in b['cuts']]


W45 = 3.0 / math.cos(math.radians(45))   # 4.2426…


class GeometryTests(unittest.TestCase):

    def test_recess(self):
        self.assertAlmostEqual(recess_mm(45, 100), 100.0, places=6)
        self.assertAlmostEqual(recess_mm(-45, 100), 100.0, places=6)
        self.assertEqual(recess_mm(0, 100), 0.0)
        self.assertEqual(recess_mm(45, 0), 0.0)

    def test_kerf_axial(self):
        self.assertEqual(kerf_axial_mm(3, 0), 3.0)
        self.assertAlmostEqual(kerf_axial_mm(3, 45), W45, places=6)
        self.assertAlmostEqual(kerf_axial_mm(3, -45), W45, places=6)

    def test_recess_profile_sides(self):
        # positive angle → far corner recessed
        self.assertEqual(end_recess_profile(45, 100), (0.0, recess_mm(45, 100)))
        # negative angle → near corner recessed
        self.assertEqual(end_recess_profile(-45, 100), (recess_mm(45, 100), 0.0))

    def test_shared_parallelogram_gap_interlocks(self):
        # A right +45 and B left -45 share one plane; boxes overlap by t - w
        gap, shared = boundary_gap_mm(45, -45, 100, 100, 3)
        self.assertTrue(shared)
        self.assertAlmostEqual(gap, W45 - 100.0, places=4)

    def test_v_notch_is_not_shared(self):
        # +45 / +45 faces form a V — two passes, plain kerf-width gap
        gap, shared = boundary_gap_mm(45, 45, 100, 100, 3)
        self.assertFalse(shared)
        self.assertAlmostEqual(gap, W45, places=4)

    def test_square_square_shared(self):
        gap, shared = boundary_gap_mm(0, 0, 0, 0, 3)
        self.assertTrue(shared)
        self.assertAlmostEqual(gap, 3.0, places=6)

    def test_angle_vs_square_not_shared_no_extra_length(self):
        # Angled face against a square face: the recess stays inside the
        # bounding box, so the gap is just the wider blade band.
        gap, shared = boundary_gap_mm(45, 0, 100, 100, 3)
        self.assertFalse(shared)
        self.assertAlmostEqual(gap, W45, places=4)

    def test_same_lean_different_magnitude_interlocks(self):
        # A right +45 (recess far), B left -30 (recess near): faces lean the
        # same way with different slopes → partial interlock allowed.
        t30 = recess_mm(30, 100)
        gap, shared = boundary_gap_mm(45, -30, 100, 100, 3)
        self.assertFalse(shared)
        self.assertAlmostEqual(gap, W45 - min(t30, 100.0), places=4)


class OptimizerPackingTests(unittest.TestCase):

    def test_square_exact_fill_no_trailing_kerf(self):
        # 2998.5 + 3 (kerf) + 2998.5 == 6000 exactly: must fit on ONE bar.
        # (The old optimizer charged a trailing kerf and opened a second bar.)
        res = optimize([part('P', 2998.5, qty=2)], 6000, kerf_mm=3)
        self.assertEqual(res['bars_needed'], 1)
        self.assertEqual(res['total_waste_mm'], 0)

    def test_parallelogram_chain_single_bar(self):
        # (+45,-45) pieces chain unflipped along shared diagonals.
        res = optimize([part('Z', 1000, qty=6, al=45, ar=-45, h=100)],
                       6000, kerf_mm=3)
        self.assertEqual(res['bars_needed'], 1)
        self.assertEqual(res['nest_pairs_formed'], 5)
        bar = res['bars'][0]
        self.assertEqual(len(bar['cuts']), 6)
        # increment per chained piece = length - t + w
        expected_used = 1000 + 5 * (1000 - 100 + W45)
        self.assertAlmostEqual(bar['used_mm'], round(expected_used, 1), places=1)
        self.assertAlmostEqual(res['material_saved_by_nesting_mm'],
                               5 * 100.0, places=1)

    def test_trapezoid_alternating_flip(self):
        # (+45,+45) pieces can only share cuts by turning every other piece
        # 180° in the miter plane.
        res = optimize([part('T', 1000, qty=4, al=45, ar=45, h=100)],
                       6000, kerf_mm=3)
        self.assertEqual(res['bars_needed'], 1)
        self.assertEqual(res['nest_pairs_formed'], 3)
        cuts = res['bars'][0]['cuts']
        self.assertEqual([c['flipped'] for c in cuts],
                         [False, True, False, True])
        self.assertEqual((cuts[1]['angle_left_deg'], cuts[1]['angle_right_deg']),
                         (-45.0, -45.0))

    def test_rotation_disabled_prevents_nesting(self):
        res = optimize(
            [part('T', 1000, qty=4, al=45, ar=45, h=100, allow_rotation=False)],
            6000, kerf_mm=3)
        self.assertEqual(res['nest_pairs_formed'], 0)
        self.assertTrue(all(not c['flipped'] for c in all_cuts(res)))

    def test_v_notch_parts_not_falsely_nested(self):
        # Old algorithm paired |right|==|left| even when the faces were NOT
        # coplanar (V notch) and charged no kerf. Must not happen.
        res = optimize(
            [part('A', 1000, al=0, ar=45, h=100),
             part('B', 1000, al=45, ar=0, h=100)],
            6000, kerf_mm=3)
        self.assertEqual(res['nest_pairs_formed'], 0)
        cuts = all_cuts(res)
        self.assertEqual(len(cuts), 2)
        self.assertFalse(cuts[1]['shared_left'])

    def test_remnant_used_before_new_bar(self):
        res = optimize(
            [part('P', 1200, qty=2)], 6000, kerf_mm=3,
            stock_pieces=[{'id': 7, 'length_mm': 2500, 'quantity': 1}])
        self.assertEqual(res['bars_needed'], 0)
        self.assertEqual(res['remnant_bars_used'], 1)
        bar = res['bars'][0]
        self.assertTrue(bar['is_remnant'])
        self.assertEqual(bar['stock_bar_id'], 7)
        # remnant gets a lead trim: offset of first piece = kerf
        self.assertAlmostEqual(bar['cuts'][0]['offset_mm'], 3.0, places=1)
        kinds = [p['kind'] for p in bar['passes']]
        self.assertEqual(kinds, ['lead', 'shared', 'end'])

    def test_oversize_piece_needs_long_remnant(self):
        res = optimize(
            [part('L', 7000)], 6000, kerf_mm=3,
            stock_pieces=[{'id': 1, 'length_mm': 8000, 'quantity': 1}])
        self.assertEqual(res['bars_needed'], 0)
        self.assertEqual(res['remnant_bars_used'], 1)
        with self.assertRaises(ValueError):
            optimize([part('L', 7000)], 6000, kerf_mm=3)

    def test_all_pieces_placed_exactly_once(self):
        parts = [
            part('A', 1750, qty=3, al=45, ar=45, h=80),
            part('B', 900, qty=5, al=-30, ar=0, h=80),
            part('C', 2400, qty=2),
            part('D', 460, qty=7, al=60, ar=-60, h=80),
        ]
        res = optimize(parts, 6000, kerf_mm=3)
        cuts = all_cuts(res)
        self.assertEqual(len(cuts), 3 + 5 + 2 + 7)
        for want, n in (('A', 3), ('B', 5), ('C', 2), ('D', 7)):
            self.assertEqual(sum(1 for c in cuts if c['label'] == want), n)

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            optimize([part('X', 1000, al=45)], 6000)          # angle, no height
        with self.assertRaises(ValueError):
            optimize([part('X', 1000, al=80, h=50)], 6000)    # too steep
        with self.assertRaises(ValueError):
            optimize([part('X', 0)], 6000)                    # zero length

    def test_impossible_geometry_rejected(self):
        # 45° recess on a 200mm profile is 200mm — the faces of a 100mm
        # piece would cross. Must be a validation error, not a garbage plan.
        with self.assertRaises(ValueError):
            optimize([part('X', 100, al=45, ar=45, h=200)], 6000)
        # Parallelogram of the same numbers is fine (recesses on opposite
        # corners never cross) — must NOT raise.
        optimize([part('OK', 250, al=45, ar=-45, h=200)], 6000)

    def test_square_boundary_shared_despite_height_mismatch(self):
        # A part with H entered next to a square part with H=0: the square
        # separating cut is height-independent and must be ONE pass.
        res = optimize(
            [part('A', 1000, h=100), part('B', 1000, h=0)], 6000, kerf_mm=3)
        bar = res['bars'][0]
        self.assertTrue(bar['cuts'][0]['shared_right'])
        kinds = [p['kind'] for p in bar['passes']]
        self.assertEqual(kinds, ['shared', 'end'])

    def test_long_point_flipped_for_lead_passes(self):
        # Lead pass: the remaining bar IS the piece side, so angle +45
        # (far corner recessed) leaves the NEAR edge protruding.
        res = optimize(
            [part('P', 1000, al=45, ar=0, h=100, allow_rotation=False)],
            6000, kerf_mm=3,
            stock_pieces=[{'id': 1, 'length_mm': 2000, 'quantity': 1}])
        passes = res['bars'][0]['passes']
        lead = [p for p in passes if p['kind'] == 'lead'][0]
        self.assertEqual(lead['long_point'], 'near')
        end = [p for p in passes if p['kind'] == 'end'][0]
        self.assertEqual(end['long_point'], 'even')   # square right end

    def test_oversize_feasibility_uses_rotation(self):
        # 7000mm piece with an angled LEFT end: as-entered the remnant lead
        # trim is kerf/cos45, rotated it is plain kerf — rotation must be
        # considered before declaring the piece unplaceable.
        res = optimize(
            [part('L', 7000, al=45, ar=0, h=100)], 6000, kerf_mm=3,
            stock_pieces=[{'id': 1, 'length_mm': 7003.5, 'quantity': 1}])
        self.assertEqual(res['remnant_bars_used'], 1)


class PassGenerationTests(unittest.TestCase):

    def test_square_pass_stops_equal_piece_lengths(self):
        res = optimize([part('P', 1000, qty=3)], 6000, kerf_mm=3)
        passes = res['bars'][0]['passes']
        self.assertEqual(len(passes), 3)
        for p in passes:
            self.assertAlmostEqual(p['stop_near_mm'], 1000.0, places=1)
            self.assertAlmostEqual(p['stop_far_mm'], 1000.0, places=1)
        self.assertEqual([p['x_near_mm'] for p in passes],
                         [1000.0, 2003.0, 3006.0])

    def test_flush_square_end_skips_final_pass(self):
        res = optimize([part('P', 2998.5, qty=2)], 6000, kerf_mm=3)
        passes = res['bars'][0]['passes']
        # single separating pass; the second piece ends at the factory end
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0]['kind'], 'shared')

    def test_angled_chain_passes(self):
        res = optimize([part('Z', 1000, qty=3, al=45, ar=-45, h=100)],
                       6000, kerf_mm=3)
        bar = res['bars'][0]
        passes = bar['passes']
        # lead (angled first face) + 2 shared + trailing end
        self.assertEqual([p['kind'] for p in passes],
                         ['lead', 'shared', 'shared', 'end'])
        for p in passes:
            self.assertAlmostEqual(abs(p['angle_deg']), 45.0, places=1)
            self.assertAlmostEqual(p['blade_axial_mm'], round(W45, 2), places=2)
        # every stop must be positive
        for p in passes[1:]:
            self.assertGreater(p['stop_near_mm'], 0)
            self.assertGreater(p['stop_far_mm'], 0)

    def test_positions_monotonic(self):
        parts = [
            part('A', 800, qty=4, al=45, ar=45, h=80),
            part('B', 650, qty=4, al=-30, ar=60, h=80),
            part('C', 1200, qty=3),
        ]
        res = optimize(parts, 6000, kerf_mm=3)
        for bar in res['bars']:
            xs = [(p['x_near_mm'] + p['x_far_mm']) / 2 for p in bar['passes']]
            self.assertEqual(xs, sorted(xs))
            for p in bar['passes']:
                self.assertGreaterEqual(p['stop_near_mm'], -0.05)
                self.assertGreaterEqual(p['stop_far_mm'], -0.05)


class FaceClearanceProperty(unittest.TestCase):
    """No blade band may cut into a neighbouring piece — for every angle
    combination the face-to-face distance must respect the clearance."""

    ANGLES = [-60, -45, -30, 0, 30, 45, 60]

    def test_pairwise_angle_sweep(self):
        H, kerf = 80.0, 3.0
        for a_r in self.ANGLES:
            for b_l in self.ANGLES:
                parts = [
                    part('A', 700, al=0, ar=a_r, h=H, allow_rotation=False),
                    part('B', 700, al=b_l, ar=0, h=H, allow_rotation=False),
                ]
                res = optimize(parts, 6000, kerf_mm=kerf)
                cuts = all_cuts(res)
                # two 700mm pieces always fit one 6000mm bar — the clearance
                # assertions below must actually run for every combination
                self.assertEqual(len(res['bars']), 1, msg=f"ar={a_r}, bl={b_l}")
                a, b = cuts
                fa = piece_faces(a['offset_mm'], a['nominal_mm'],
                                 a['angle_left_deg'], a['angle_right_deg'],
                                 a['profile_height_mm'])
                fb = piece_faces(b['offset_mm'], b['nominal_mm'],
                                 b['angle_left_deg'], b['angle_right_deg'],
                                 b['profile_height_mm'])
                d_near = fb['left'][0] - fa['right'][0]
                d_far = fb['left'][1] - fa['right'][1]
                clearance = max(kerf_axial_mm(kerf, a['angle_right_deg']),
                                kerf_axial_mm(kerf, b['angle_left_deg']))
                self.assertGreaterEqual(
                    min(d_near, d_far), clearance - 0.11,   # rounding slack
                    msg=f"faces too close for ar={a_r}, bl={b_l}")
                # pieces stay inside the bar
                for c in cuts:
                    self.assertGreaterEqual(c['offset_mm'], -0.01)
                    self.assertLessEqual(c['end_mm'],
                                         res['bars'][0]['stock_length_mm'] + 0.01)


class ProductionRegressionTests(unittest.TestCase):
    """Regressions found with real production data (copper pipe job 292-02)."""

    PARTS = [
        part('POZ-17', 1685, qty=6, al=45, ar=-45, h=70, job_no='292-02'),
        part('POZ-18', 1615, qty=6, job_no='292-02'),
        part('POZ-19', 1280, qty=6, job_no='292-02'),
        part('POZ-21', 1060, qty=3, job_no='292-02'),
        part('POZ-26', 1015, qty=2, al=45, ar=45, h=70, job_no='292-02'),
    ]

    def test_efficiency_never_exceeds_100(self):
        # Interlocked parallelogram chains double-count the shared diagonal
        # in bounding lengths; efficiency must use true material content.
        res = optimize(self.PARTS, 6000, kerf_mm=3)
        self.assertLessEqual(res['efficiency_pct'], 100.0)
        self.assertGreater(res['efficiency_pct'], 50.0)
        # pure parallelogram chain, tight case
        res2 = optimize([part('Z', 1685, qty=30, al=45, ar=-45, h=70)],
                        6000, kerf_mm=3)
        self.assertLessEqual(res2['efficiency_pct'], 100.0)

    def test_angle_families_consolidated_when_material_equal(self):
        # 4 square beams fill bar 1; the two small parallelograms must end up
        # nested together (one shared diagonal) on the second bar, keeping
        # every square pass at one saw setting and both 45° passes at one
        # setting — not scattered between square parts.
        parts = [
            part('KARE', 1400, qty=4),
            part('PARA', 500, qty=2, al=45, ar=-45, h=70),
        ]
        res = optimize(parts, 6000, kerf_mm=3)
        self.assertEqual(res['bars_needed'], 2)
        self.assertEqual(res['nest_pairs_formed'], 1)
        self.assertIn('saw_setup_changes', res)
        # a parallelogram pair cut at one setting after squares-only bars:
        # no mid-bar setting changes anywhere
        self.assertEqual(res['saw_setup_changes'], 0)
        for bar in res['bars']:
            angles = {abs(c['angle_left_deg']) for c in bar['cuts']}
            angles |= {abs(c['angle_right_deg']) for c in bar['cuts']}
            self.assertIn(angles, ({0.0}, {45.0}))   # no mixed bars here

    def test_no_negative_zero_stops(self):
        res = optimize(self.PARTS, 6000, kerf_mm=3)
        for bar in res['bars']:
            for p in bar['passes']:
                for key in ('stop_near_mm', 'stop_far_mm',
                            'x_near_mm', 'x_far_mm'):
                    val = p[key]
                    self.assertGreaterEqual(val, 0.0, msg=f"{key}={val}")
                    self.assertNotEqual(str(val), '-0.0')


class BackCompatKeysTests(unittest.TestCase):

    def test_result_keys(self):
        res = optimize([part('P', 1000, qty=2, al=45, ar=0, h=50)], 6000)
        for key in ('bars_needed', 'remnant_bars_used', 'total_waste_mm',
                    'efficiency_pct', 'bars', 'nest_pairs_formed',
                    'material_saved_by_nesting_mm'):
            self.assertIn(key, res)
        bar = res['bars'][0]
        for key in ('bar_index', 'stock_length_mm', 'waste_mm', 'is_remnant',
                    'stock_bar_id', 'cuts', 'passes'):
            self.assertIn(key, bar)
        cut = bar['cuts'][0]
        for key in ('label', 'nominal_mm', 'effective_mm', 'offset_mm',
                    'end_mm', 'job_no', 'part_id', 'angle_left_deg',
                    'angle_right_deg', 'profile_height_mm', 'flipped',
                    'shared_left', 'shared_right', 'requires_bending'):
            self.assertIn(key, cut)

    def test_empty_parts(self):
        res = optimize([], 6000)
        self.assertEqual(res['bars'], [])
        self.assertEqual(res['bars_needed'], 0)


if __name__ == '__main__':
    unittest.main()
