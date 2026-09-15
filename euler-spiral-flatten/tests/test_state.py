
"""Black-box tests for cubic Bezier curve flattener.

Only the public API flatten_cubic is tested — no assumptions about
internal implementation structure, algorithms, or helper functions.
"""

import sys
sys.path.insert(0, '/app')

import math
import pytest

from geometry import Vec2, eval_cubic, max_error_to_polyline
from flattener import flatten_cubic

KAPPA = 0.5522847498  # standard quarter-circle control point weight


# -----------------------------------------------------------------------
# Endpoint preservation
# -----------------------------------------------------------------------
class TestEndpoints:
    """First and last polyline points must match the input control points."""

    def test_preserves_start_point(self):
        p0 = Vec2(1.5, 2.3)
        pts = flatten_cubic(p0, Vec2(2, 5), Vec2(4, 0), Vec2(5, 7), tolerance=0.1)
        assert abs(pts[0][0] - p0.x) < 1e-6
        assert abs(pts[0][1] - p0.y) < 1e-6

    def test_preserves_end_point(self):
        p3 = Vec2(5, 7)
        pts = flatten_cubic(Vec2(1.5, 2.3), Vec2(2, 5), Vec2(4, 0), p3, tolerance=0.1)
        assert abs(pts[-1][0] - p3.x) < 1e-6
        assert abs(pts[-1][1] - p3.y) < 1e-6

    def test_preserves_both_across_curves(self):
        curves = [
            (Vec2(0, 0), Vec2(1, 1), Vec2(2, 1), Vec2(3, 0)),
            (Vec2(-1, -1), Vec2(0, 2), Vec2(3, -1), Vec2(4, 4)),
            (Vec2(10, 20), Vec2(11, 25), Vec2(14, 15), Vec2(15, 20)),
        ]
        for p0, p1, p2, p3 in curves:
            pts = flatten_cubic(p0, p1, p2, p3, tolerance=0.05)
            assert abs(pts[0][0] - p0.x) < 1e-6 and abs(pts[0][1] - p0.y) < 1e-6
            assert abs(pts[-1][0] - p3.x) < 1e-6 and abs(pts[-1][1] - p3.y) < 1e-6


# -----------------------------------------------------------------------
# Error bounds — the polyline must approximate the curve within tolerance
# -----------------------------------------------------------------------
class TestErrorBounds:

    def test_quarter_circle_multiple_tolerances(self):
        p0, p1 = Vec2(1, 0), Vec2(1, KAPPA)
        p2, p3 = Vec2(KAPPA, 1), Vec2(0, 1)
        for tol in [0.1, 0.05, 0.01]:
            pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
            err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=500)
            assert err <= tol * 2.0, f"tol={tol}: error {err:.6f} exceeds {tol * 2}"

    def test_s_curve(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(1, 2), Vec2(2, -2), Vec2(3, 0)
        for tol in [0.1, 0.05]:
            pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
            err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=500)
            assert err <= tol * 2.0, f"tol={tol}: error {err:.6f}"

    def test_tight_u_shape(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(0, 2), Vec2(2, 2), Vec2(2, 0)
        for tol in [0.05, 0.01]:
            pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
            err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=500)
            assert err <= tol * 2.0, f"tol={tol}: error {err:.6f}"

    def test_wide_arch(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(0, 3), Vec2(3, 3), Vec2(3, 0)
        tol = 0.05
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
        err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=500)
        assert err <= tol * 2.0

    def test_gentle_bend(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(1, 0.1), Vec2(2, 0.1), Vec2(3, 0)
        tol = 0.01
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
        err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=300)
        assert err <= tol * 2.0

    def test_strong_s_curve(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(1, 3), Vec2(2, -3), Vec2(3, 0)
        tol = 0.05
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
        err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=600)
        assert err <= tol * 2.0

    def test_asymmetric_curve(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(0.5, 3), Vec2(2.5, -1), Vec2(4, 2)
        tol = 0.05
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
        err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=500)
        assert err <= tol * 2.0

    def test_multiple_curves_tight_tol(self):
        """Comprehensive error check across a batch of diverse curves."""
        curves = [
            (Vec2(0, 0), Vec2(1, 1), Vec2(2, 1), Vec2(3, 0)),
            (Vec2(0, 0), Vec2(0, 3), Vec2(3, 3), Vec2(3, 0)),
            (Vec2(0, 0), Vec2(1, 0.1), Vec2(2, 0.1), Vec2(3, 0)),
            (Vec2(0, 0), Vec2(2, 0), Vec2(1, 2), Vec2(3, 1)),
        ]
        tol = 0.02
        for p0, p1, p2, p3 in curves:
            pts = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
            err = max_error_to_polyline(p0, p1, p2, p3, pts, n_samples=400)
            assert err <= tol * 2.0, (
                f"Error {err:.6f} for curve ({p0},{p1},{p2},{p3})"
            )


# -----------------------------------------------------------------------
# Efficiency — must outperform naive recursive subdivision
# -----------------------------------------------------------------------
class TestEfficiency:

    def test_aggregate_fewer_than_naive(self):
        """Across diverse curved inputs at a tight tolerance, the
        implementation must produce meaningfully fewer total segments
        than the naive recursive subdivision baseline."""
        from naive_flatten import flatten_cubic_naive
        curves = [
            (Vec2(1, 0), Vec2(1, KAPPA), Vec2(KAPPA, 1), Vec2(0, 1)),
            (Vec2(0, 0), Vec2(0, 3), Vec2(3, 3), Vec2(3, 0)),
            (Vec2(0, 0), Vec2(1, 3), Vec2(2, -3), Vec2(3, 0)),
            (Vec2(0, 0), Vec2(0.5, 2), Vec2(1.5, 2), Vec2(2, 0)),
        ]
        tol = 0.005
        total_new = 0
        total_naive = 0
        for p0, p1, p2, p3 in curves:
            pts_new = flatten_cubic(p0, p1, p2, p3, tolerance=tol)
            pts_naive = flatten_cubic_naive(p0, p1, p2, p3, tolerance=tol)
            total_new += max(len(pts_new) - 1, 1)
            total_naive += max(len(pts_naive) - 1, 1)
        ratio = total_new / total_naive
        assert ratio < 0.85, (
            f"Not efficient enough: new={total_new} segments, "
            f"naive={total_naive} segments, ratio={ratio:.3f} (need <0.85)"
        )

    def test_straight_line_minimal_segments(self):
        pts = flatten_cubic(Vec2(0, 0), Vec2(1, 0), Vec2(2, 0), Vec2(3, 0))
        assert len(pts) <= 3, f"Straight line: got {len(pts)} points, want <= 3"

    def test_quarter_circle_bounded_count(self):
        """A single quarter circle at moderate tolerance must not
        produce an excessive number of segments."""
        p0, p1 = Vec2(1, 0), Vec2(1, KAPPA)
        p2, p3 = Vec2(KAPPA, 1), Vec2(0, 1)
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=0.01)
        assert 3 <= len(pts) <= 25, f"Got {len(pts)} points, want 3..25"

    def test_no_trivial_copy_of_naive(self):
        """Specific curve where a curvature-aware approach should
        produce fewer segments than naive for a tight tolerance."""
        from naive_flatten import flatten_cubic_naive
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(0, 3), Vec2(3, 3), Vec2(3, 0)
        tol = 0.002
        n_new = len(flatten_cubic(p0, p1, p2, p3, tolerance=tol)) - 1
        n_naive = len(flatten_cubic_naive(p0, p1, p2, p3, tolerance=tol)) - 1
        assert n_new < n_naive, (
            f"Must produce fewer segments than naive: "
            f"new={n_new}, naive={n_naive}"
        )


# -----------------------------------------------------------------------
# Robustness — degenerate inputs must not crash or produce invalid output
# -----------------------------------------------------------------------
class TestRobustness:

    def test_cusp_self_intersecting(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(1, 1), Vec2(0, 1), Vec2(1, 0)
        pts = flatten_cubic(p0, p1, p2, p3, tolerance=0.1)
        assert len(pts) >= 2
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)

    def test_zero_length_all_coincident(self):
        p = Vec2(1, 1)
        pts = flatten_cubic(p, p, p, p, tolerance=0.1)
        assert len(pts) >= 1
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)

    def test_near_collinear(self):
        pts = flatten_cubic(
            Vec2(0, 0), Vec2(1, 1e-10), Vec2(2, -1e-10), Vec2(3, 0),
            tolerance=0.1
        )
        assert len(pts) >= 2
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)

    def test_coincident_start_control_point(self):
        """p0 == p1 gives zero initial derivative."""
        p0 = Vec2(0, 0)
        pts = flatten_cubic(p0, p0, Vec2(1, 1), Vec2(2, 0), tolerance=0.1)
        assert len(pts) >= 2
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)

    def test_coincident_end_control_point(self):
        """p2 == p3 gives zero final derivative."""
        p3 = Vec2(2, 0)
        pts = flatten_cubic(Vec2(0, 0), Vec2(1, 1), p3, p3, tolerance=0.1)
        assert len(pts) >= 2
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)

    def test_very_short_curve(self):
        """Nearly-zero-length but not exactly zero."""
        p0, p3 = Vec2(0, 0), Vec2(1e-9, 1e-9)
        pts = flatten_cubic(p0, Vec2(0.5e-9, 0), Vec2(0, 0.5e-9), p3, tolerance=0.1)
        assert len(pts) >= 1
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)


# -----------------------------------------------------------------------
# Tolerance scaling
# -----------------------------------------------------------------------
class TestScaling:

    def test_tighter_tolerance_yields_more_segments(self):
        p0, p1, p2, p3 = Vec2(0, 0), Vec2(0, 1), Vec2(1, 1), Vec2(1, 0)
        pts_coarse = flatten_cubic(p0, p1, p2, p3, tolerance=1.0)
        pts_fine = flatten_cubic(p0, p1, p2, p3, tolerance=0.01)
        assert len(pts_fine) > len(pts_coarse), (
            f"Fine ({len(pts_fine)}) should be > coarse ({len(pts_coarse)})"
        )

    def test_monotonic_across_three_levels(self):
        p0, p1 = Vec2(1, 0), Vec2(1, KAPPA)
        p2, p3 = Vec2(KAPPA, 1), Vec2(0, 1)
        tols = [1.0, 0.1, 0.01]
        counts = [len(flatten_cubic(p0, p1, p2, p3, tolerance=t)) for t in tols]
        for i in range(len(counts) - 1):
            assert counts[i + 1] >= counts[i], (
                f"Non-monotonic: tol={tols[i]} gave {counts[i]}, "
                f"tol={tols[i + 1]} gave {counts[i + 1]}"
            )


# -----------------------------------------------------------------------
# Output format
# -----------------------------------------------------------------------
class TestOutputFormat:

    def test_returns_list_of_coordinate_tuples(self):
        pts = flatten_cubic(Vec2(0, 0), Vec2(1, 1), Vec2(2, 0), Vec2(3, 1))
        assert isinstance(pts, list)
        assert len(pts) >= 2
        assert isinstance(pts[0], (tuple, list))
        assert len(pts[0]) == 2

    def test_all_coordinates_finite(self):
        pts = flatten_cubic(
            Vec2(0, 0), Vec2(1, 2), Vec2(2, -1), Vec2(3, 0), tolerance=0.05
        )
        for pt in pts:
            assert math.isfinite(pt[0]) and math.isfinite(pt[1])
